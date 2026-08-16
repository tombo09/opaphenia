import logging
import threading
import time
import uuid
from datetime import datetime, timezone

from psycopg.types.json import Jsonb

from app.db import connect
from app import utils
from app.config import ETH_CONFIRMATIONS


logger = logging.getLogger(__name__)

_signer_state_lock = threading.Lock()
_signer_available = None

CLAIM_SECONDS = 90
LEASE_RENEW_INTERVAL_SECONDS = 30
RECOVERY_INTERVAL_SECONDS = 5
ETHEREUM_CHAIN_ID = 1
UNRESOLVED_WARNING_RETRIES = 10
NOT_FOUND_REBROADCAST_THRESHOLD = 2
RECOVERABLE_STATUSES = (
    "pending",
    "prepared",
    "needs_reconciliation",
    "broadcast",
    "confirming",
)


def _record_signer_availability(available: bool) -> None:
    global _signer_available
    with _signer_state_lock:
        previous = _signer_available
        if previous is available:
            return
        _signer_available = available

    if not available:
        logger.error(
            "Ethereum signing is disabled: ETH_PK is missing or invalid; "
            "pending thoughts will remain unchanged"
        )
    elif previous is False:
        logger.info("Ethereum signing is available; pending recovery resumed")


def _backoff_seconds(retry_count: int) -> int:
    return min(300, 2 ** min(retry_count, 8))


def _get_thought(thought_id: int):
    con = connect()
    try:
        with con.cursor() as cur:
            cur.execute(
                """
                SELECT id, status, wallet_address, eth_nonce, raw_transaction,
                       txid, retry_count, next_retry_at
                FROM thoughts
                WHERE id = %s
                """,
                (thought_id,),
            )
            return cur.fetchone()
    finally:
        con.close()


def _claim(thought_id: int, statuses: tuple[str, ...]):
    claim_id = uuid.uuid4().hex
    con = connect()
    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    """
                    UPDATE thoughts
                    SET claimed_by = %s,
                        claim_until = now() + (%s * interval '1 second'),
                        updated_at = now()
                    WHERE id = %s
                      AND status = ANY(%s)
                      AND (next_retry_at IS NULL OR next_retry_at <= now())
                      AND (claim_until IS NULL OR claim_until < now())
                    RETURNING id, status, wallet_address, eth_nonce,
                              raw_transaction, txid, retry_count, receipt,
                              confirmation_required, confirmation_count,
                              confirmation_block_number,
                              confirmation_block_hash
                    """,
                    (claim_id, CLAIM_SECONDS, thought_id, list(statuses)),
                )
                row = cur.fetchone()
                if row:
                    row["claim_id"] = claim_id
                return row
    finally:
        con.close()


def _schedule_retry(
    thought_id: int,
    claim_id: str,
    status: str,
    exc: Exception,
    sensitive_values=(),
    wallet_address=None,
    wallet_owner=None,
):
    message = utils.sanitize_rpc_text(exc, sensitive_values=sensitive_values)
    row = None
    con = connect()
    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    """
                    UPDATE thoughts
                    SET status = %s,
                        retry_count = retry_count + 1,
                        last_error = %s,
                        next_retry_at = now() + (
                            %s * interval '1 second'
                        ),
                        claimed_by = NULL,
                        claim_until = NULL,
                        updated_at = now()
                    WHERE id = %s AND claimed_by = %s
                      AND (
                          %s::text IS NULL
                          OR EXISTS (
                              SELECT 1
                              FROM ethereum_wallet_state
                              WHERE wallet_address = %s
                                AND broadcast_claimed_by = %s
                                AND broadcast_claim_until > now()
                          )
                      )
                    RETURNING retry_count, wallet_address, eth_nonce, txid
                    """,
                    (
                        status,
                        message,
                        _backoff_seconds(1),
                        thought_id,
                        claim_id,
                        wallet_owner,
                        wallet_address,
                        wallet_owner,
                    ),
                )
                row = cur.fetchone()
                if row:
                    retry_count = row["retry_count"]
                    cur.execute(
                        """
                        UPDATE thoughts
                        SET next_retry_at = now() + (%s * interval '1 second')
                        WHERE id = %s
                        """,
                        (_backoff_seconds(retry_count), thought_id),
                    )
    finally:
        con.close()

    if row and row["retry_count"] >= UNRESOLVED_WARNING_RETRIES:
        logger.error(
            "Ethereum thought unresolved: thought_id=%s txid=%s "
            "nonce=%s message=%s",
            thought_id,
            row["txid"],
            row["eth_nonce"],
            message,
        )


def _release_claim(thought_id: int, claim_id: str) -> None:
    con = connect()
    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    """
                    UPDATE thoughts
                    SET claimed_by = NULL, claim_until = NULL, updated_at = now()
                    WHERE id = %s AND claimed_by = %s
                    """,
                    (thought_id, claim_id),
                )
    finally:
        con.close()


def _schedule_broadcast_poll(
    thought_id: int,
    claim_id: str,
    message: str,
    *,
    not_found: bool = False,
) -> str | None:
    """Persist a polling result and return the resulting delivery status."""
    con = connect()
    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    """
                    UPDATE thoughts
                    SET consecutive_not_found = CASE
                            WHEN %s THEN consecutive_not_found + 1
                            ELSE 0
                        END,
                        status = CASE
                            WHEN %s AND consecutive_not_found + 1 >= %s
                                THEN 'needs_reconciliation'
                            ELSE 'broadcast'
                        END,
                        retry_count = retry_count + 1,
                        last_error = %s,
                        next_retry_at = CASE
                            WHEN %s AND consecutive_not_found + 1 >= %s
                                THEN NULL
                            ELSE now() + (%s * interval '1 second')
                        END,
                        claimed_by = NULL, claim_until = NULL,
                        updated_at = now()
                    WHERE id = %s AND claimed_by = %s
                      AND status = 'broadcast'
                    RETURNING status, retry_count
                    """,
                    (
                        not_found,
                        not_found,
                        NOT_FOUND_REBROADCAST_THRESHOLD,
                        utils.sanitize_rpc_text(message),
                        not_found,
                        NOT_FOUND_REBROADCAST_THRESHOLD,
                        _backoff_seconds(1),
                        thought_id,
                        claim_id,
                    ),
                )
                row = cur.fetchone()
                if not row:
                    return None
                if row["status"] == "broadcast":
                    cur.execute(
                        """
                        UPDATE thoughts
                        SET next_retry_at = now() + (%s * interval '1 second')
                        WHERE id = %s AND claimed_by IS NULL
                        """,
                        (_backoff_seconds(row["retry_count"]), thought_id),
                    )
                return row["status"]
    finally:
        con.close()


def _receipt_metadata(receipt: dict) -> dict:
    fields = (
        "transactionHash",
        "status",
        "blockHash",
        "blockNumber",
        "from",
        "to",
        "gasUsed",
        "cumulativeGasUsed",
        "effectiveGasPrice",
        "contractAddress",
        "type",
    )
    return {field: receipt.get(field) for field in fields if field in receipt}


def _validate_receipt(claimed, receipt: dict) -> int:
    if not isinstance(receipt, dict):
        raise RuntimeError("Invalid Ethereum receipt")

    receipt_txid = receipt.get("transactionHash")
    if not isinstance(receipt_txid, str) or (
        receipt_txid.lower() != claimed["txid"].lower()
    ):
        raise RuntimeError("Ethereum receipt transaction hash mismatch")

    try:
        receipt_status = int(receipt.get("status"), 16)
    except (TypeError, ValueError):
        raise RuntimeError("Ethereum receipt status is invalid") from None
    if receipt_status not in (0, 1):
        raise RuntimeError("Ethereum receipt status is invalid")

    expected_address = claimed["wallet_address"].lower()
    for field in ("from", "to"):
        value = receipt.get(field)
        if value is not None and (
            not isinstance(value, str) or value.lower() != expected_address
        ):
            raise RuntimeError(f"Ethereum receipt {field} address mismatch")

    chain_id = int(utils.rpc_call("eth_chainId", []), 16)
    if chain_id != ETHEREUM_CHAIN_ID:
        raise RuntimeError(f"not Mainnet (chainId={chain_id})")
    return receipt_status


def _mark_receipt_outcome(
    thought_id: int,
    claim_id: str,
    receipt: dict,
    blocktime,
    status: str,
) -> bool:
    if status != "reverted":
        raise ValueError("Invalid receipt outcome")
    con = connect()
    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    """
                    UPDATE thoughts
                    SET status = %s, receipt = %s, blocktime = %s,
                        confirmation_required = NULL,
                        confirmation_count = NULL,
                        confirmation_block_number = NULL,
                        confirmation_block_hash = NULL,
                        consecutive_not_found = 0, retry_count = 0,
                        last_error = NULL, next_retry_at = NULL,
                        claimed_by = NULL, claim_until = NULL,
                        updated_at = now()
                    WHERE id = %s AND claimed_by = %s
                      AND status IN ('broadcast', 'confirming')
                    """,
                    (
                        status,
                        Jsonb(_receipt_metadata(receipt)),
                        blocktime,
                        thought_id,
                        claim_id,
                    ),
                )
                return cur.rowcount == 1
    finally:
        con.close()


def _confirmation_data(receipt: dict):
    block_number_hex = receipt.get("blockNumber")
    block_hash = receipt.get("blockHash")
    if not isinstance(block_number_hex, str) or not isinstance(block_hash, str):
        raise RuntimeError("Ethereum receipt block identity is invalid")
    block_number = int(block_number_hex, 16)

    block = utils.rpc_call("eth_getBlockByNumber", [block_number_hex, False])
    if block is None:
        raise ReorgDetected("Ethereum receipt block disappeared")
    canonical_hash = block.get("hash")
    if not isinstance(canonical_hash, str) or (
        canonical_hash.lower() != block_hash.lower()
    ):
        raise ReorgDetected("Ethereum receipt block is no longer canonical")

    latest_number = int(utils.rpc_call("eth_blockNumber", []), 16)
    confirmation_count = max(0, latest_number - block_number + 1)
    blocktime = datetime.fromtimestamp(
        int(block["timestamp"], 16),
        tz=timezone.utc,
    )
    return block_number, block_hash, confirmation_count, blocktime


class ReorgDetected(RuntimeError):
    pass


def _mark_confirming(
    thought_id: int,
    claim_id: str,
    receipt: dict,
    blocktime,
    block_number: int,
    block_hash: str,
    confirmation_count: int,
) -> bool:
    con = connect()
    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    """
                    UPDATE thoughts
                    SET status = 'confirming', receipt = %s, blocktime = %s,
                        published_at = COALESCE(published_at, now()),
                        confirmation_required = %s, confirmation_count = %s,
                        confirmation_block_number = %s,
                        confirmation_block_hash = %s,
                        consecutive_not_found = 0, retry_count = 0,
                        last_error = NULL, next_retry_at = NULL,
                        claimed_by = NULL, claim_until = NULL,
                        updated_at = now()
                    WHERE id = %s AND claimed_by = %s
                      AND status = 'broadcast'
                    """,
                    (
                        Jsonb(_receipt_metadata(receipt)),
                        blocktime,
                        ETH_CONFIRMATIONS,
                        confirmation_count,
                        block_number,
                        block_hash,
                        thought_id,
                        claim_id,
                    ),
                )
                return cur.rowcount == 1
    finally:
        con.close()


def _update_confirming(
    thought_id: int,
    claim_id: str,
    receipt: dict,
    blocktime,
    block_number: int,
    block_hash: str,
    confirmation_count: int,
    *,
    mined: bool,
) -> bool:
    con = connect()
    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    """
                    UPDATE thoughts
                    SET status = %s, receipt = %s, blocktime = %s,
                        confirmation_count = %s,
                        confirmation_block_number = %s,
                        confirmation_block_hash = %s,
                        retry_count = 0, last_error = NULL,
                        next_retry_at = NULL, claimed_by = NULL,
                        claim_until = NULL, updated_at = now()
                    WHERE id = %s AND claimed_by = %s
                      AND status = 'confirming'
                    """,
                    (
                        "mined" if mined else "confirming",
                        Jsonb(_receipt_metadata(receipt)),
                        blocktime,
                        confirmation_count,
                        block_number,
                        block_hash,
                        thought_id,
                        claim_id,
                    ),
                )
                return cur.rowcount == 1
    finally:
        con.close()


def _recover_from_reorg(thought_id: int, claim_id: str, message: str) -> bool:
    con = connect()
    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    """
                    UPDATE thoughts
                    SET status = 'needs_reconciliation', receipt = NULL,
                        blocktime = NULL, confirmation_required = NULL,
                        confirmation_count = NULL, retry_count = 0,
                        confirmation_block_number = NULL,
                        confirmation_block_hash = NULL,
                        last_error = %s, next_retry_at = NULL,
                        claimed_by = NULL, claim_until = NULL,
                        updated_at = now()
                    WHERE id = %s AND claimed_by = %s
                      AND status = 'confirming'
                    """,
                    (utils.sanitize_rpc_text(message), thought_id, claim_id),
                )
                return cur.rowcount == 1
    finally:
        con.close()


def _schedule_confirming_retry(
    thought_id: int, claim_id: str, message: str
) -> bool:
    con = connect()
    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    """
                    UPDATE thoughts
                    SET retry_count = retry_count + 1, last_error = %s,
                        next_retry_at = now() + (%s * interval '1 second'),
                        claimed_by = NULL, claim_until = NULL,
                        updated_at = now()
                    WHERE id = %s AND claimed_by = %s
                      AND status = 'confirming'
                    """,
                    (
                        utils.sanitize_rpc_text(message),
                        _backoff_seconds(1),
                        thought_id,
                        claim_id,
                    ),
                )
                return cur.rowcount == 1
    finally:
        con.close()


def _claim_wallet_broadcast(
    wallet_address: str,
    nonce: int,
    claim_id: str,
) -> bool:
    con = connect()
    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    """
                    UPDATE ethereum_wallet_state
                    SET broadcast_claimed_by = %s,
                        broadcast_claim_until = now() + (%s * interval '1 second'),
                        updated_at = now()
                    WHERE wallet_address = %s
                      AND (
                          broadcast_claim_until IS NULL
                          OR broadcast_claim_until < now()
                      )
                      AND NOT EXISTS (
                          SELECT 1
                          FROM thoughts
                          WHERE thoughts.wallet_address = %s
                            AND thoughts.eth_nonce < %s
                            AND thoughts.status IN (
                                'prepared', 'needs_reconciliation'
                            )
                      )
                    """,
                    (
                        claim_id,
                        CLAIM_SECONDS,
                        wallet_address,
                        wallet_address,
                        nonce,
                    ),
                )
                return cur.rowcount == 1
    finally:
        con.close()


def _release_wallet_broadcast(wallet_address: str, claim_id: str) -> None:
    con = connect()
    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    """
                    UPDATE ethereum_wallet_state
                    SET broadcast_claimed_by = NULL,
                        broadcast_claim_until = NULL,
                        updated_at = now()
                    WHERE wallet_address = %s AND broadcast_claimed_by = %s
                    """,
                    (wallet_address, claim_id),
                )
    finally:
        con.close()


def _renew_wallet_broadcast(
    wallet_address: str,
    wallet_owner: str,
    thought_id: int,
    thought_claim: str,
) -> bool:
    con = connect()
    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    """
                    UPDATE ethereum_wallet_state
                    SET broadcast_claim_until = now() + (
                            %s * interval '1 second'
                        ),
                        updated_at = now()
                    WHERE wallet_address = %s
                      AND broadcast_claimed_by = %s
                    """,
                    (CLAIM_SECONDS, wallet_address, wallet_owner),
                )
                if cur.rowcount != 1:
                    raise RuntimeError("wallet lease ownership lost")
                cur.execute(
                    """
                    UPDATE thoughts
                    SET claim_until = now() + (%s * interval '1 second'),
                        updated_at = now()
                    WHERE id = %s AND claimed_by = %s
                    """,
                    (CLAIM_SECONDS, thought_id, thought_claim),
                )
                if cur.rowcount != 1:
                    raise RuntimeError("thought lease ownership lost")
        return True
    except Exception:
        return False
    finally:
        con.close()


class _WalletLeaseGuard:
    def __init__(
        self,
        wallet_address: str,
        wallet_owner: str,
        thought_id: int,
        thought_claim: str,
    ):
        self.wallet_address = wallet_address
        self.wallet_owner = wallet_owner
        self.thought_id = thought_id
        self.thought_claim = thought_claim
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._thread = threading.Thread(
            target=self._renew_loop,
            name="wallet-lease-renewal",
            daemon=True,
        )

    def start(self):
        self._thread.start()
        return self

    def _renew_loop(self):
        while not self._stop.wait(LEASE_RENEW_INTERVAL_SECONDS):
            if not self.renew():
                return

    def renew(self) -> bool:
        if self._lost.is_set():
            return False
        owned = _renew_wallet_broadcast(
            self.wallet_address,
            self.wallet_owner,
            self.thought_id,
            self.thought_claim,
        )
        if not owned:
            self._lost.set()
        return owned

    def close(self):
        self._stop.set()
        self._thread.join(timeout=LEASE_RENEW_INTERVAL_SECONDS + 1)
        _release_wallet_broadcast(self.wallet_address, self.wallet_owner)


def _load_chain_parameters(hashed_string: str, signer: utils.EthereumSigner):
    chain_id = int(utils.rpc_call("eth_chainId", []), 16)
    if chain_id != ETHEREUM_CHAIN_ID:
        raise RuntimeError(f"not Mainnet (chainId={chain_id})")

    latest = utils.rpc_call("eth_getBlockByNumber", ["latest", False])
    base_fee = int(latest["baseFeePerGas"], 16)
    priority = 2 * 10**8
    max_fee = base_fee + 2 * priority
    estimate = {
        "from": signer.address,
        "to": signer.address,
        "value": hex(0),
        "data": hashed_string,
        "maxFeePerGas": hex(max_fee),
        "maxPriorityFeePerGas": hex(priority),
    }
    gas = int(utils.rpc_call("eth_estimateGas", [estimate]), 16)
    chain_nonce = int(
        utils.rpc_call("eth_getTransactionCount", [signer.address, "pending"]),
        16,
    )
    return chain_id, gas, max_fee, priority, chain_nonce


def prepare_thought(
    thought_id: int, signer: utils.EthereumSigner | None = None
) -> bool:
    # Resolve configuration before claiming the durable row. A missing/invalid
    # key must leave pending state, retry counters, and leases untouched.
    if signer is None:
        signer = utils.get_ethereum_signer()
    claimed = _claim(thought_id, ("pending",))
    if not claimed:
        return False

    con = connect()
    try:
        with con.cursor() as cur:
            cur.execute(
                "SELECT hashed_string FROM thoughts WHERE id = %s",
                (thought_id,),
            )
            hashed_string = cur.fetchone()["hashed_string"]
    finally:
        con.close()

    try:
        chain_id, gas, max_fee, priority, chain_nonce = _load_chain_parameters(
            hashed_string, signer
        )
    except Exception as exc:
        _schedule_retry(thought_id, claimed["claim_id"], "pending", exc)
        return False

    con = connect()
    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"ethereum-wallet:{signer.address.lower()}",),
                )
                cur.execute(
                    """
                    SELECT status, claimed_by
                    FROM thoughts
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (thought_id,),
                )
                current = cur.fetchone()
                if not current or current["status"] != "pending" or current["claimed_by"] != claimed["claim_id"]:
                    return False

                cur.execute(
                    """
                    SELECT 1
                    FROM thoughts
                    WHERE wallet_address = %s
                      AND id <> %s
                      AND status IN ('prepared', 'needs_reconciliation')
                    LIMIT 1
                    """,
                    (signer.address.lower(), thought_id),
                )
                if cur.fetchone():
                    raise RuntimeError(
                        "wallet has an unresolved prepared transaction"
                    )

                cur.execute(
                    """
                    INSERT INTO ethereum_wallet_state (wallet_address, next_nonce)
                    VALUES (%s, %s)
                    ON CONFLICT (wallet_address) DO NOTHING
                    """,
                    (signer.address.lower(), chain_nonce),
                )
                cur.execute(
                    """
                    SELECT next_nonce
                    FROM ethereum_wallet_state
                    WHERE wallet_address = %s
                    FOR UPDATE
                    """,
                    (signer.address.lower(),),
                )
                nonce = max(chain_nonce, cur.fetchone()["next_nonce"])

                tx = {
                    "type": 2,
                    "chainId": chain_id,
                    "nonce": nonce,
                    "to": signer.address,
                    "value": 0,
                    "data": hashed_string,
                    "gas": gas,
                    "maxFeePerGas": max_fee,
                    "maxPriorityFeePerGas": priority,
                }
                signed = signer.account.sign_transaction(tx)
                raw_transaction = bytes(signed.raw_transaction)
                txid = signed.hash.hex()
                if not txid.startswith("0x"):
                    txid = "0x" + txid

                cur.execute(
                    """
                    UPDATE ethereum_wallet_state
                    SET next_nonce = %s, updated_at = now()
                    WHERE wallet_address = %s
                    """,
                    (nonce + 1, signer.address.lower()),
                )
                cur.execute(
                    """
                    UPDATE thoughts
                    SET status = 'prepared', wallet_address = %s,
                        eth_nonce = %s, raw_transaction = %s, txid = %s,
                        retry_count = 0, last_error = NULL,
                        next_retry_at = NULL, claimed_by = NULL,
                        claim_until = NULL, updated_at = now()
                    WHERE id = %s AND status = 'pending' AND claimed_by = %s
                    """,
                    (
                        signer.address.lower(),
                        nonce,
                        raw_transaction,
                        txid,
                        thought_id,
                        claimed["claim_id"],
                    ),
                )
        return True
    except Exception as exc:
        _schedule_retry(thought_id, claimed["claim_id"], "pending", exc)
        return False
    finally:
        con.close()


def _mark_broadcast(
    thought_id: int,
    claim_id: str,
    wallet_address: str,
    wallet_owner: str,
) -> bool:
    con = connect()
    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    """
                    UPDATE thoughts
                    SET status = 'broadcast', retry_count = 0,
                        consecutive_not_found = 0,
                        last_error = NULL, next_retry_at = NULL,
                        claimed_by = NULL, claim_until = NULL,
                        updated_at = now()
                    WHERE id = %s AND claimed_by = %s
                      AND status IN ('prepared', 'needs_reconciliation')
                      AND EXISTS (
                          SELECT 1
                          FROM ethereum_wallet_state
                          WHERE wallet_address = %s
                            AND broadcast_claimed_by = %s
                            AND broadcast_claim_until > now()
                      )
                    """,
                    (thought_id, claim_id, wallet_address, wallet_owner),
                )
                return cur.rowcount == 1
    finally:
        con.close()


def broadcast_thought(thought_id: int) -> bool:
    claimed = _claim(thought_id, ("prepared", "needs_reconciliation"))
    if not claimed:
        return False

    txid = claimed["txid"]
    wallet_address = claimed["wallet_address"]
    wallet_owner = uuid.uuid4().hex
    if not _claim_wallet_broadcast(
        wallet_address,
        claimed["eth_nonce"],
        wallet_owner,
    ):
        _release_claim(thought_id, claimed["claim_id"])
        return False
    lease = _WalletLeaseGuard(
        wallet_address,
        wallet_owner,
        thought_id,
        claimed["claim_id"],
    ).start()
    try:
        if not lease.renew():
            return False
        known = utils.rpc_call("eth_getTransactionByHash", [txid])
        if known is None:
            if not lease.renew():
                return False
            raw_hex = "0x" + bytes(claimed["raw_transaction"]).hex()
            utils.rpc_call("eth_sendRawTransaction", [raw_hex])
        if not lease.renew():
            return False
        return _mark_broadcast(
            thought_id,
            claimed["claim_id"],
            wallet_address,
            wallet_owner,
        )
    except Exception as exc:
        if not lease.renew():
            return False
        try:
            known = utils.rpc_call("eth_getTransactionByHash", [txid])
        except Exception:
            known = None
        if not lease.renew():
            return False
        if known is not None:
            return _mark_broadcast(
                thought_id,
                claimed["claim_id"],
                wallet_address,
                wallet_owner,
            )
        _schedule_retry(
            thought_id,
            claimed["claim_id"],
            "needs_reconciliation",
            exc,
            sensitive_values=(
                "0x" + bytes(claimed["raw_transaction"]).hex(),
            ),
            wallet_address=wallet_address,
            wallet_owner=wallet_owner,
        )
        return False
    finally:
        lease.close()


def confirm_thought(thought_id: int, wait: bool = False) -> bool:
    claimed = _claim(thought_id, ("broadcast", "confirming"))
    if not claimed:
        return False

    if claimed["status"] == "confirming":
        try:
            receipt = utils.rpc_call(
                "eth_getTransactionReceipt", [claimed["txid"]]
            )
            if receipt is None:
                return _recover_from_reorg(
                    thought_id,
                    claimed["claim_id"],
                    "Ethereum receipt disappeared before finality",
                )

            receipt_status = _validate_receipt(claimed, receipt)
            (
                block_number,
                block_hash,
                confirmation_count,
                blocktime,
            ) = _confirmation_data(receipt)

            if receipt_status == 0:
                return _mark_receipt_outcome(
                    thought_id,
                    claimed["claim_id"],
                    receipt,
                    blocktime,
                    "reverted",
                )

            placement_changed = (
                claimed["confirmation_block_number"] != block_number
                or str(claimed["confirmation_block_hash"] or "").lower()
                != block_hash.lower()
            )
            if placement_changed:
                return _update_confirming(
                    thought_id,
                    claimed["claim_id"],
                    receipt,
                    blocktime,
                    block_number,
                    block_hash,
                    confirmation_count,
                    mined=False,
                )

            required = claimed["confirmation_required"] or ETH_CONFIRMATIONS
            return _update_confirming(
                thought_id,
                claimed["claim_id"],
                receipt,
                blocktime,
                block_number,
                block_hash,
                confirmation_count,
                mined=confirmation_count >= required,
            )
        except ReorgDetected as exc:
            return _recover_from_reorg(
                thought_id, claimed["claim_id"], str(exc)
            )
        except Exception as exc:
            _schedule_confirming_retry(
                thought_id, claimed["claim_id"], str(exc)
            )
            return False

    started_at = time.time()
    while True:
        try:
            receipt = utils.rpc_call(
                "eth_getTransactionReceipt", [claimed["txid"]]
            )
            if receipt is not None:
                receipt_status = _validate_receipt(claimed, receipt)
                (
                    block_number,
                    block_hash,
                    confirmation_count,
                    blocktime,
                ) = _confirmation_data(receipt)
                if receipt_status == 0:
                    return _mark_receipt_outcome(
                        thought_id,
                        claimed["claim_id"],
                        receipt,
                        blocktime,
                        "reverted",
                    )
                return _mark_confirming(
                    thought_id,
                    claimed["claim_id"],
                    receipt,
                    blocktime,
                    block_number,
                    block_hash,
                    confirmation_count,
                )

            known = utils.rpc_call(
                "eth_getTransactionByHash", [claimed["txid"]]
            )
        except Exception as exc:
            _schedule_broadcast_poll(
                thought_id, claimed["claim_id"], str(exc)
            )
            return False

        if known is not None and wait and time.time() - started_at <= 120:
            time.sleep(3)
            continue
        break

    status = _schedule_broadcast_poll(
        thought_id,
        claimed["claim_id"],
        (
            "Transaction not found"
            if known is None
            else "Transaction is still pending"
        ),
        not_found=known is None,
    )
    if status == "needs_reconciliation":
        return broadcast_thought(thought_id)
    return False


def process_thought(
    thought_id: int,
    wait_for_receipt: bool = False,
    signer: utils.EthereumSigner | None = None,
):
    row = _get_thought(thought_id)
    if not row:
        return None
    if row["status"] == "pending":
        prepare_thought(thought_id, signer=signer)
        row = _get_thought(thought_id)
    if row and row["status"] in ("prepared", "needs_reconciliation"):
        broadcast_thought(thought_id)
        row = _get_thought(thought_id)
    if row and row["status"] == "broadcast":
        confirm_thought(thought_id, wait=wait_for_receipt)
    elif row and row["status"] == "confirming":
        confirm_thought(thought_id, wait=False)
    return _get_thought(thought_id)


def recover_once(limit: int = 20) -> int:
    try:
        signer = utils.get_ethereum_signer()
        _record_signer_availability(True)
    except utils.EthereumConfigurationError:
        signer = None
        _record_signer_availability(False)

    con = connect()
    try:
        with con.cursor() as cur:
            cur.execute(
                """
                SELECT id
                FROM thoughts
                WHERE status = ANY(%s)
                  AND (next_retry_at IS NULL OR next_retry_at <= now())
                  AND (claim_until IS NULL OR claim_until < now())
                ORDER BY
                    CASE status
                        WHEN 'prepared' THEN 0
                        WHEN 'needs_reconciliation' THEN 0
                        WHEN 'broadcast' THEN 1
                        WHEN 'confirming' THEN 1
                        ELSE 2
                    END,
                    eth_nonce NULLS LAST,
                    created_at
                LIMIT %s
                """,
                (
                    list(RECOVERABLE_STATUSES)
                    if signer is not None
                    else [
                        status
                        for status in RECOVERABLE_STATUSES
                        if status != "pending"
                    ],
                    limit,
                ),
            )
            thought_ids = [row["id"] for row in cur.fetchall()]
    finally:
        con.close()

    for thought_id in thought_ids:
        try:
            process_thought(
                thought_id, wait_for_receipt=False, signer=signer
            )
        except Exception:
            logger.error("Thought recovery failed: thought_id=%s", thought_id)
    return len(thought_ids)


def start_recovery_worker():
    stop_event = threading.Event()

    def run():
        while not stop_event.is_set():
            try:
                recover_once()
            except Exception:
                logger.error("Thought recovery loop failed")
            stop_event.wait(RECOVERY_INTERVAL_SECONDS)

    thread = threading.Thread(
        target=run,
        name="thought-recovery",
        daemon=True,
    )
    thread.start()
    return stop_event, thread
