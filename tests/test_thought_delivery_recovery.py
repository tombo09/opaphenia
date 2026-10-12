import hashlib
import io
import os
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from dotenv import load_dotenv


ROOT = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(ROOT, ".env"))
os.environ.setdefault("ETH_PK", "0x" + "1" * 64)

from fastapi import HTTPException

from app import thought_delivery, utils
from app.db import connect
from app.migrations import run_migrations
from app.routers import thoughts
from app.routers import public
from app.schemas import ThoughtIn


class FakeHash:
    def __init__(self, value):
        self.value = value

    def hex(self):
        return "0x" + self.value.hex()


class FakeSignedTransaction:
    def __init__(self, raw):
        self.raw_transaction = raw
        self.hash = FakeHash(hashlib.sha256(raw).digest())


class FakeAccount:
    def __init__(self):
        self.sign_calls = 0

    def sign_transaction(self, transaction):
        self.sign_calls += 1
        raw = transaction["nonce"].to_bytes(8, "big") + bytes.fromhex(
            transaction["data"].removeprefix("0x")
        )
        return FakeSignedTransaction(raw)


class FakeChain:
    def __init__(self):
        self.transactions = {}
        self.send_calls = 0
        self.sent_raw = []
        self.pending_nonce = 0
        self.lose_next_send_response = False
        self.current_block = 1
        self.block_hashes = {1: "0x" + "01" * 32}

    def _block(self, number):
        block_hash = self.block_hashes.get(number)
        if block_hash is None:
            return None
        return {
            "number": hex(number),
            "hash": block_hash,
            "timestamp": hex(100 + number),
            "baseFeePerGas": "0x1",
        }

    def txid_for_raw(self, raw_hex):
        raw = bytes.fromhex(raw_hex.removeprefix("0x"))
        return "0x" + hashlib.sha256(raw).hexdigest()

    def rpc_call(self, method, params):
        if method == "eth_chainId":
            return "0x1"
        if method == "eth_getBlockByNumber" and params[0] == "latest":
            return self._block(self.current_block)
        if method == "eth_getBlockByNumber":
            return self._block(int(params[0], 16))
        if method == "eth_blockNumber":
            return hex(self.current_block)
        if method == "eth_estimateGas":
            return "0x5208"
        if method == "eth_getTransactionCount":
            return hex(self.pending_nonce)
        if method == "eth_getTransactionByHash":
            return self.transactions.get(params[0])
        if method == "eth_getTransactionReceipt":
            tx = self.transactions.get(params[0])
            if tx is None or tx["blockNumber"] is None:
                return None
            return {
                "transactionHash": params[0],
                "blockNumber": tx["blockNumber"],
                "blockHash": tx["blockHash"],
                "status": "0x1",
            }
        if method == "eth_sendRawTransaction":
            self.send_calls += 1
            self.sent_raw.append(params[0])
            txid = self.txid_for_raw(params[0])
            nonce = int.from_bytes(
                bytes.fromhex(params[0].removeprefix("0x"))[:8], "big"
            )
            self.pending_nonce = max(self.pending_nonce, nonce + 1)
            self.transactions.setdefault(
                txid,
                {"hash": txid, "blockNumber": None, "blockHash": None},
            )
            if self.lose_next_send_response:
                self.lose_next_send_response = False
                raise TimeoutError("RPC response was lost")
            return txid
        raise AssertionError(f"Unexpected RPC method: {method}")

    def mine(self, txid, block_number=None):
        number = self.current_block if block_number is None else block_number
        self.current_block = max(self.current_block, number)
        self.block_hashes.setdefault(number, "0x" + f"{number:064x}")
        self.transactions[txid]["blockNumber"] = hex(number)
        self.transactions[txid]["blockHash"] = self.block_hashes[number]

    def advance(self, count=1):
        for number in range(self.current_block + 1, self.current_block + count + 1):
            self.block_hashes[number] = "0x" + f"{number:064x}"
        self.current_block += count


class ThoughtDeliveryRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            run_migrations()
            con = connect()
            con.close()
        except Exception as exc:
            raise unittest.SkipTest(f"PostgreSQL is unavailable: {exc}")

    def setUp(self):
        suffix = uuid.uuid4().hex
        self.wallet = "0x" + suffix[:40].ljust(40, "0")
        con = connect()
        try:
            with con:
                with con.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO users
                            (email, username, password_hash, email_verified)
                        VALUES (%s, %s, 'unused', TRUE)
                        RETURNING id
                        """,
                        (f"{suffix}@example.test", f"user_{suffix}"),
                    )
                    self.user_id = cur.fetchone()["id"]
        finally:
            con.close()

    def tearDown(self):
        con = connect()
        try:
            with con:
                with con.cursor() as cur:
                    cur.execute("DELETE FROM users WHERE id = %s", (self.user_id,))
                    cur.execute(
                        "DELETE FROM ethereum_wallet_state WHERE wallet_address = %s",
                        (self.wallet.lower(),),
                    )
        finally:
            con.close()

    def insert_pending(self, key=None):
        con = connect()
        try:
            with con:
                with con.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO thoughts
                            (user_id, content, hashed_string, status,
                             idempotency_key, wallet_address)
                        VALUES (%s, 'content', '0x01', 'pending', %s, %s)
                        RETURNING id
                        """,
                        (self.user_id, key or uuid.uuid4().hex, self.wallet.lower()),
                    )
                    return cur.fetchone()["id"]
        finally:
            con.close()

    def get_delivery_row(self, thought_id):
        con = connect()
        try:
            with con.cursor() as cur:
                cur.execute(
                    """
                    SELECT status, eth_nonce, raw_transaction, txid,
                           idempotency_key, receipt, consecutive_not_found,
                           confirmation_required, confirmation_count,
                           confirmation_block_number,
                           confirmation_block_hash, published_at
                    FROM thoughts WHERE id = %s
                    """,
                    (thought_id,),
                )
                return cur.fetchone()
        finally:
            con.close()

    def delivery_patches(self, chain):
        account = FakeAccount()
        signer = utils.EthereumSigner(account=account, address=self.wallet)
        return (
            patch.object(utils, "get_ethereum_signer", return_value=signer),
            patch.object(utils, "get_ethereum_signer", return_value=signer),
            patch.object(utils, "rpc_call", side_effect=chain.rpc_call),
            account,
        )

    def test_crash_after_pending_commit_is_recovered(self):
        with (
            patch.object(thoughts, "moderate_text", return_value={"flagged": False}),
            patch.object(thoughts, "process_thought", return_value=None),
        ):
            response = thoughts.create_thought(
                ThoughtIn(content="durable pending"),
                user_id=self.user_id,
                idempotency_key="pending-crash",
            )

        row = self.get_delivery_row(response["id"])
        self.assertEqual(row["status"], "pending")

        chain = FakeChain()
        with self.delivery_patches(chain)[0], self.delivery_patches(chain)[1], self.delivery_patches(chain)[2]:
            thought_delivery.process_thought(response["id"])

        self.assertEqual(self.get_delivery_row(response["id"])["status"], "broadcast")
        self.assertEqual(chain.send_calls, 1)

    def test_missing_signer_warning_is_logged_only_on_state_transition(self):
        signer_error = utils.EthereumConfigurationError("signer unavailable")
        thought_delivery._signer_available = None
        with (
            patch.object(
                utils,
                "get_ethereum_signer",
                side_effect=signer_error,
            ),
            self.assertLogs(thought_delivery.logger, level="ERROR") as missing_logs,
        ):
            thought_delivery.recover_once()
            thought_delivery.recover_once()

        warnings = [
            message
            for message in missing_logs.output
            if "Ethereum signing is disabled" in message
        ]
        self.assertEqual(len(warnings), 1)

        signer = utils.EthereumSigner(account=FakeAccount(), address=self.wallet)
        with (
            patch.object(utils, "get_ethereum_signer", return_value=signer),
            self.assertLogs(thought_delivery.logger, level="INFO") as restored_logs,
        ):
            thought_delivery.recover_once()
            thought_delivery.recover_once()

        restored = [
            message
            for message in restored_logs.output
            if "Ethereum signing is available" in message
        ]
        self.assertEqual(len(restored), 1)

    def test_crash_after_prepared_commit_reuses_prepared_transaction(self):
        thought_id = self.insert_pending()
        chain = FakeChain()
        patches = self.delivery_patches(chain)
        with patches[0], patches[1], patches[2]:
            self.assertTrue(thought_delivery.prepare_thought(thought_id))
            prepared = self.get_delivery_row(thought_id)
            self.assertEqual(prepared["status"], "prepared")
            self.assertIsNotNone(prepared["raw_transaction"])
            self.assertTrue(thought_delivery.broadcast_thought(thought_id))
            self.assertTrue(thought_delivery.broadcast_thought(thought_id) is False)

        self.assertEqual(chain.send_calls, 1)
        self.assertEqual(self.get_delivery_row(thought_id)["eth_nonce"], 0)

    def test_lost_rpc_response_does_not_send_second_transaction(self):
        thought_id = self.insert_pending()
        chain = FakeChain()
        patches = self.delivery_patches(chain)
        with patches[0], patches[1], patches[2]:
            thought_delivery.prepare_thought(thought_id)
            chain.lose_next_send_response = True
            self.assertTrue(thought_delivery.broadcast_thought(thought_id))
            self.assertEqual(self.get_delivery_row(thought_id)["status"], "broadcast")
            thought_delivery.process_thought(thought_id)

        self.assertEqual(chain.send_calls, 1)

    def test_crash_after_broadcast_before_status_update_is_reconciled(self):
        thought_id = self.insert_pending()
        chain = FakeChain()
        patches = self.delivery_patches(chain)
        with patches[0], patches[1], patches[2]:
            thought_delivery.prepare_thought(thought_id)
            prepared = self.get_delivery_row(thought_id)
            raw_hex = "0x" + bytes(prepared["raw_transaction"]).hex()
            chain.rpc_call("eth_sendRawTransaction", [raw_hex])
            self.assertEqual(self.get_delivery_row(thought_id)["status"], "prepared")
            thought_delivery.broadcast_thought(thought_id)

        self.assertEqual(chain.send_calls, 1)
        self.assertEqual(self.get_delivery_row(thought_id)["status"], "broadcast")

    def test_crash_after_mining_before_database_update_is_recovered(self):
        thought_id = self.insert_pending()
        chain = FakeChain()
        patches = self.delivery_patches(chain)
        with patches[0], patches[1], patches[2], patch.object(
            thought_delivery, "ETH_CONFIRMATIONS", 2
        ):
            thought_delivery.prepare_thought(thought_id)
            thought_delivery.broadcast_thought(thought_id)
            txid = self.get_delivery_row(thought_id)["txid"]
            chain.mine(txid)
            self.assertEqual(self.get_delivery_row(thought_id)["status"], "broadcast")
            self.assertTrue(thought_delivery.confirm_thought(thought_id))
            confirming = self.get_delivery_row(thought_id)
            self.assertEqual(confirming["status"], "confirming")
            self.assertIsNotNone(confirming["published_at"])
            self.assertEqual(confirming["confirmation_count"], 1)
            self.assertEqual(confirming["confirmation_required"], 2)
            chain.advance()
            self.assertTrue(thought_delivery.confirm_thought(thought_id))

        self.assertEqual(self.get_delivery_row(thought_id)["status"], "mined")
        self.assertEqual(
            self.get_delivery_row(thought_id)["receipt"]["transactionHash"],
            txid,
        )

    def test_failed_receipt_transitions_to_reverted_never_mined(self):
        thought_id = self.insert_pending()
        chain = FakeChain()
        patches = self.delivery_patches(chain)
        with patches[0], patches[1], patches[2]:
            thought_delivery.prepare_thought(thought_id)
            thought_delivery.broadcast_thought(thought_id)
            txid = self.get_delivery_row(thought_id)["txid"]
            chain.mine(txid)

            original_rpc = chain.rpc_call

            def reverted_rpc(method, params):
                result = original_rpc(method, params)
                if method == "eth_getTransactionReceipt" and result:
                    return {**result, "status": "0x0"}
                return result

            with patch.object(utils, "rpc_call", side_effect=reverted_rpc):
                self.assertTrue(thought_delivery.confirm_thought(thought_id))

        row = self.get_delivery_row(thought_id)
        self.assertEqual(row["status"], "reverted")
        self.assertEqual(row["receipt"]["status"], "0x0")
        self.assertIsNone(row["published_at"])

    def test_insufficient_confirmations_stay_confirming_until_depth(self):
        thought_id = self.insert_pending()
        chain = FakeChain()
        patches = self.delivery_patches(chain)
        with patches[0], patches[1], patches[2], patch.object(
            thought_delivery, "ETH_CONFIRMATIONS", 3
        ):
            thought_delivery.prepare_thought(thought_id)
            thought_delivery.broadcast_thought(thought_id)
            txid = self.get_delivery_row(thought_id)["txid"]
            chain.mine(txid)

            self.assertTrue(thought_delivery.confirm_thought(thought_id))
            first = self.get_delivery_row(thought_id)
            self.assertEqual(first["status"], "confirming")
            self.assertEqual(first["confirmation_count"], 1)
            self.assertEqual(first["confirmation_block_number"], 1)
            self.assertEqual(
                first["confirmation_block_hash"], chain.block_hashes[1]
            )

            chain.advance()
            self.assertTrue(thought_delivery.confirm_thought(thought_id))
            second = self.get_delivery_row(thought_id)
            self.assertEqual(second["status"], "confirming")
            self.assertEqual(second["confirmation_count"], 2)

            chain.advance()
            self.assertTrue(thought_delivery.confirm_thought(thought_id))

        self.assertEqual(self.get_delivery_row(thought_id)["status"], "mined")

    def test_receipt_disappears_before_finality_preserving_transaction(self):
        thought_id = self.insert_pending()
        chain = FakeChain()
        patches = self.delivery_patches(chain)
        with patches[0], patches[1], patches[2], patch.object(
            thought_delivery, "ETH_CONFIRMATIONS", 3
        ):
            thought_delivery.prepare_thought(thought_id)
            thought_delivery.broadcast_thought(thought_id)
            before = self.get_delivery_row(thought_id)
            chain.mine(before["txid"])
            thought_delivery.confirm_thought(thought_id)
            chain.transactions[before["txid"]]["blockNumber"] = None

            self.assertTrue(thought_delivery.confirm_thought(thought_id))

        recovered = self.get_delivery_row(thought_id)
        self.assertEqual(recovered["status"], "needs_reconciliation")
        self.assertIsNotNone(recovered["published_at"])
        self.assertEqual(recovered["eth_nonce"], before["eth_nonce"])
        self.assertEqual(recovered["txid"], before["txid"])
        self.assertEqual(
            bytes(recovered["raw_transaction"]),
            bytes(before["raw_transaction"]),
        )
        self.assertIsNone(recovered["confirmation_block_number"])

        con = connect()
        try:
            with con:
                with con.cursor() as cur:
                    cur.execute(
                        "UPDATE users SET strings_public = TRUE WHERE id = %s",
                        (self.user_id,),
                    )
        finally:
            con.close()
        self.assertEqual(public.get_public_thought(thought_id)["id"], thought_id)

    def test_default_confirmation_depth_remains_twelve(self):
        thought_id = self.insert_pending()
        chain = FakeChain()
        patches = self.delivery_patches(chain)
        with patches[0], patches[1], patches[2], patch.object(
            thought_delivery, "ETH_CONFIRMATIONS", 12
        ):
            thought_delivery.prepare_thought(thought_id)
            thought_delivery.broadcast_thought(thought_id)
            txid = self.get_delivery_row(thought_id)["txid"]
            chain.mine(txid)
            self.assertTrue(thought_delivery.confirm_thought(thought_id))
            self.assertEqual(self.get_delivery_row(thought_id)["status"], "confirming")
            self.assertIsNotNone(self.get_delivery_row(thought_id)["published_at"])

            chain.advance(10)
            self.assertTrue(thought_delivery.confirm_thought(thought_id))
            self.assertEqual(self.get_delivery_row(thought_id)["status"], "confirming")

            chain.advance()
            self.assertTrue(thought_delivery.confirm_thought(thought_id))

        self.assertEqual(self.get_delivery_row(thought_id)["status"], "mined")

    def test_reorged_transaction_new_block_restarts_confirmation(self):
        thought_id = self.insert_pending()
        chain = FakeChain()
        patches = self.delivery_patches(chain)
        with patches[0], patches[1], patches[2], patch.object(
            thought_delivery, "ETH_CONFIRMATIONS", 2
        ):
            thought_delivery.prepare_thought(thought_id)
            thought_delivery.broadcast_thought(thought_id)
            txid = self.get_delivery_row(thought_id)["txid"]
            chain.mine(txid)
            thought_delivery.confirm_thought(thought_id)

            chain.advance()
            chain.mine(txid, block_number=2)
            self.assertTrue(thought_delivery.confirm_thought(thought_id))

            moved = self.get_delivery_row(thought_id)
            self.assertEqual(moved["status"], "confirming")
            self.assertEqual(moved["confirmation_block_number"], 2)
            self.assertEqual(moved["confirmation_count"], 1)

            chain.advance()
            self.assertTrue(thought_delivery.confirm_thought(thought_id))

        self.assertEqual(self.get_delivery_row(thought_id)["status"], "mined")

    def test_recovery_resumes_confirmation_and_confirming_is_public(self):
        thought_id = self.insert_pending(key="confirming-proof")
        chain = FakeChain()
        patches = self.delivery_patches(chain)
        with patches[0], patches[1], patches[2], patch.object(
            thought_delivery, "ETH_CONFIRMATIONS", 2
        ):
            thought_delivery.prepare_thought(thought_id)
            thought_delivery.broadcast_thought(thought_id)
            chain.mine(self.get_delivery_row(thought_id)["txid"])
            thought_delivery.confirm_thought(thought_id)

            con = connect()
            try:
                with con.transaction():
                    with con.cursor() as cur:
                        cur.execute(
                            "UPDATE users SET strings_public = TRUE WHERE id = %s",
                            (self.user_id,),
                        )
            finally:
                con.close()

            public_detail = public.get_public_thought(thought_id)
            self.assertEqual(public_detail["id"], thought_id)
            public_items = public.public_thoughts_by_user(self.user_id)["items"]
            self.assertIn(thought_id, [item["id"] for item in public_items])

            chain.advance()
            self.assertGreaterEqual(thought_delivery.recover_once(), 1)

        self.assertEqual(self.get_delivery_row(thought_id)["status"], "mined")

    def test_mismatched_receipt_hash_is_rejected_without_terminal_transition(self):
        thought_id = self.insert_pending()
        chain = FakeChain()
        patches = self.delivery_patches(chain)
        with patches[0], patches[1], patches[2]:
            thought_delivery.prepare_thought(thought_id)
            thought_delivery.broadcast_thought(thought_id)
            txid = self.get_delivery_row(thought_id)["txid"]
            chain.mine(txid)

            original_rpc = chain.rpc_call

            def mismatched_rpc(method, params):
                result = original_rpc(method, params)
                if method == "eth_getTransactionReceipt" and result:
                    return {
                        **result,
                        "transactionHash": "0x" + "f" * 64,
                    }
                return result

            with patch.object(utils, "rpc_call", side_effect=mismatched_rpc):
                self.assertFalse(thought_delivery.confirm_thought(thought_id))

        row = self.get_delivery_row(thought_id)
        self.assertEqual(row["status"], "broadcast")
        self.assertIsNone(row["receipt"])

    def test_reverted_nonce_does_not_block_next_transaction(self):
        first_id = self.insert_pending()
        chain = FakeChain()
        patches = self.delivery_patches(chain)
        with patches[0], patches[1], patches[2]:
            thought_delivery.prepare_thought(first_id)
            thought_delivery.broadcast_thought(first_id)
            first_txid = self.get_delivery_row(first_id)["txid"]
            chain.mine(first_txid)

            original_rpc = chain.rpc_call

            def reverted_rpc(method, params):
                result = original_rpc(method, params)
                if method == "eth_getTransactionReceipt" and result:
                    return {**result, "status": "0x0"}
                return result

            with patch.object(utils, "rpc_call", side_effect=reverted_rpc):
                thought_delivery.confirm_thought(first_id)

            second_id = self.insert_pending()
            self.assertTrue(thought_delivery.prepare_thought(second_id))

        self.assertEqual(self.get_delivery_row(first_id)["status"], "reverted")
        self.assertEqual(self.get_delivery_row(second_id)["eth_nonce"], 1)

    def test_reverted_counts_toward_quota_and_is_not_public(self):
        reverted_id = self.insert_pending(key="reverted-proof")
        con = connect()
        try:
            with con.transaction():
                with con.cursor() as cur:
                    cur.execute(
                        "UPDATE thoughts SET status = 'reverted' WHERE id = %s",
                        (reverted_id,),
                    )
                    cur.execute(
                        "UPDATE users SET strings_public = TRUE WHERE id = %s",
                        (self.user_id,),
                    )
        finally:
            con.close()

        with (
            patch.object(thoughts, "moderate_text", return_value={"flagged": False}),
            patch.object(
                thoughts,
                "process_thought",
                return_value={"status": "pending"},
            ),
        ):
            second = thoughts.create_thought(
                ThoughtIn(content="second quota thought"),
                user_id=self.user_id,
                idempotency_key="quota-second",
            )
            with self.assertRaises(HTTPException) as raised:
                thoughts.create_thought(
                    ThoughtIn(content="third quota thought"),
                    user_id=self.user_id,
                    idempotency_key="quota-third",
                )

        self.assertEqual(second["status"], "pending")
        self.assertEqual(raised.exception.status_code, 429)
        with self.assertRaises(HTTPException) as public_error:
            public.get_public_thought(reverted_id)
        self.assertEqual(public_error.exception.status_code, 404)
        public_items = public.public_thoughts_by_user(self.user_id)["items"]
        self.assertNotIn(reverted_id, [item["id"] for item in public_items])

    def test_disappeared_broadcast_rebroadcasts_stored_transaction(self):
        thought_id = self.insert_pending()
        chain = FakeChain()
        patches = self.delivery_patches(chain)
        account = patches[3]
        with patches[0], patches[1], patches[2]:
            self.assertTrue(thought_delivery.prepare_thought(thought_id))
            prepared = self.get_delivery_row(thought_id)
            raw_hex = "0x" + bytes(prepared["raw_transaction"]).hex()
            nonce = prepared["eth_nonce"]
            txid = prepared["txid"]
            self.assertTrue(thought_delivery.broadcast_thought(thought_id))

            chain.transactions.pop(txid)
            self.assertFalse(thought_delivery.confirm_thought(thought_id))
            first_missing = self.get_delivery_row(thought_id)
            self.assertEqual(first_missing["status"], "broadcast")
            self.assertEqual(chain.send_calls, 1)

            con = connect()
            try:
                with con:
                    with con.cursor() as cur:
                        cur.execute(
                            "UPDATE thoughts SET next_retry_at = NULL WHERE id = %s",
                            (thought_id,),
                        )
            finally:
                con.close()

            self.assertTrue(thought_delivery.confirm_thought(thought_id))

        recovered = self.get_delivery_row(thought_id)
        self.assertEqual(recovered["status"], "broadcast")
        self.assertEqual(recovered["eth_nonce"], nonce)
        self.assertEqual(recovered["txid"], txid)
        self.assertEqual(account.sign_calls, 1)
        self.assertEqual(chain.send_calls, 2)
        self.assertEqual(chain.sent_raw, [raw_hex, raw_hex])

    def test_pending_broadcast_is_not_rebroadcast(self):
        thought_id = self.insert_pending()
        chain = FakeChain()
        patches = self.delivery_patches(chain)
        account = patches[3]
        with patches[0], patches[1], patches[2]:
            thought_delivery.prepare_thought(thought_id)
            thought_delivery.broadcast_thought(thought_id)
            txid = self.get_delivery_row(thought_id)["txid"]
            self.assertIsNotNone(chain.transactions[txid])
            self.assertFalse(thought_delivery.confirm_thought(thought_id))

        row = self.get_delivery_row(thought_id)
        self.assertEqual(row["status"], "broadcast")
        self.assertEqual(row["consecutive_not_found"], 0)
        self.assertEqual(chain.send_calls, 1)
        self.assertEqual(account.sign_calls, 1)

    def test_duplicate_idempotency_key_creates_one_record(self):
        barrier = threading.Barrier(2)

        def submit():
            barrier.wait()
            return thoughts.create_thought(
                ThoughtIn(content="same content"),
                user_id=self.user_id,
                idempotency_key="same-key",
            )["id"]

        with (
            patch.object(thoughts, "moderate_text", return_value={"flagged": False}),
            patch.object(
                thoughts,
                "process_thought",
                return_value={"status": "pending"},
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            ids = list(executor.map(lambda _: submit(), range(2)))

        self.assertEqual(ids[0], ids[1])

    def test_durable_duplicate_bypasses_moderation_and_resumes(self):
        moderation = unittest.mock.Mock(return_value={"flagged": False})
        with (
            patch.object(thoughts, "moderate_text", moderation),
            patch.object(
                thoughts,
                "process_thought",
                return_value={"status": "pending"},
            ) as delivery,
        ):
            first = thoughts.create_thought(
                ThoughtIn(content="  same normalized content  "),
                user_id=self.user_id,
                idempotency_key="durable-retry-key",
            )
            moderation.side_effect = RuntimeError("moderation unavailable")
            duplicate = thoughts.create_thought(
                ThoughtIn(content="same normalized content"),
                user_id=self.user_id,
                idempotency_key="durable-retry-key",
            )

        self.assertEqual(first["id"], duplicate["id"])
        self.assertEqual(moderation.call_count, 1)
        self.assertEqual(delivery.call_count, 0)

    def test_duplicate_different_content_returns_409_without_moderation(self):
        moderation = unittest.mock.Mock(return_value={"flagged": False})
        with (
            patch.object(thoughts, "moderate_text", moderation),
            patch.object(
                thoughts,
                "process_thought",
                return_value={"status": "pending"},
            ),
        ):
            thoughts.create_thought(
                ThoughtIn(content="first content"),
                user_id=self.user_id,
                idempotency_key="different-content-key",
            )
            with self.assertRaises(HTTPException) as raised:
                thoughts.create_thought(
                    ThoughtIn(content="different content"),
                    user_id=self.user_id,
                    idempotency_key="different-content-key",
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(moderation.call_count, 1)

    def test_duplicate_does_not_consume_daily_quota_twice(self):
        with (
            patch.object(
                thoughts,
                "moderate_text",
                return_value={"flagged": False},
            ),
            patch.object(
                thoughts,
                "process_thought",
                return_value={"status": "pending"},
            ),
        ):
            first = thoughts.create_thought(
                ThoughtIn(content="quota first"),
                user_id=self.user_id,
                idempotency_key="quota-idempotent-key",
            )
            duplicate = thoughts.create_thought(
                ThoughtIn(content="quota first"),
                user_id=self.user_id,
                idempotency_key="quota-idempotent-key",
            )
            second = thoughts.create_thought(
                ThoughtIn(content="quota second"),
                user_id=self.user_id,
                idempotency_key="quota-distinct-key",
            )
            with self.assertRaises(HTTPException) as raised:
                thoughts.create_thought(
                    ThoughtIn(content="quota third"),
                    user_id=self.user_id,
                    idempotency_key="quota-overflow-key",
                )

        self.assertEqual(first["id"], duplicate["id"])
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(raised.exception.status_code, 429)

    def test_moderation_failure_creates_no_thought(self):
        key = "moderation-failure-key"
        with patch.object(
            thoughts,
            "moderate_text",
            side_effect=RuntimeError("moderation unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                thoughts.create_thought(
                    ThoughtIn(content="new unavailable submission"),
                    user_id=self.user_id,
                    idempotency_key=key,
                )

        con = connect()
        try:
            with con.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM thoughts
                    WHERE user_id = %s AND idempotency_key = %s
                    """,
                    (self.user_id, key),
                )
                self.assertEqual(cur.fetchone()["count"], 0)
        finally:
            con.close()

    def test_same_idempotency_key_with_different_content_returns_409(self):
        with (
            patch.object(thoughts, "moderate_text", return_value={"flagged": False}),
            patch.object(
                thoughts,
                "process_thought",
                return_value={"status": "pending"},
            ),
        ):
            thoughts.create_thought(
                ThoughtIn(content="first"),
                user_id=self.user_id,
                idempotency_key="reused-key",
            )
            with self.assertRaises(HTTPException) as raised:
                thoughts.create_thought(
                    ThoughtIn(content="different"),
                    user_id=self.user_id,
                    idempotency_key="reused-key",
                )

        self.assertEqual(raised.exception.status_code, 409)

    def test_echoed_raw_transaction_is_redacted_everywhere(self):
        thought_id = self.insert_pending()
        chain = FakeChain()
        patches = self.delivery_patches(chain)
        with patches[0], patches[1], patches[2]:
            thought_delivery.prepare_thought(thought_id)

        row = self.get_delivery_row(thought_id)
        raw_hex = "0x" + bytes(row["raw_transaction"]).hex()

        class EchoingResponse:
            status_code = 200
            ok = True

            def __init__(self, data):
                self.data = data

            def json(self):
                return self.data

        def echoing_post(url, json, timeout):
            if json["method"] == "eth_sendRawTransaction":
                return EchoingResponse(
                    {
                        "error": {
                            "code": -32000,
                            "message": f"rejected transaction {raw_hex}",
                        }
                    }
                )
            return EchoingResponse({"result": None})

        with self.assertRaises(utils.RPCError) as raised:
            with patch.object(utils.requests, "post", side_effect=echoing_post):
                utils.rpc_call("eth_sendRawTransaction", [raw_hex])
        self.assertNotIn(raw_hex, str(raised.exception))

        con = connect()
        try:
            with con:
                with con.cursor() as cur:
                    cur.execute(
                        "UPDATE thoughts SET retry_count = 9 WHERE id = %s",
                        (thought_id,),
                    )
        finally:
            con.close()

        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.object(utils.requests, "post", side_effect=echoing_post),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
            self.assertLogs(thought_delivery.logger, level="ERROR") as logs,
        ):
            thought_delivery.broadcast_thought(thought_id)

        con = connect()
        try:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT last_error FROM thoughts WHERE id = %s",
                    (thought_id,),
                )
                last_error = cur.fetchone()["last_error"]
        finally:
            con.close()

        own_api_response = public.get_own_thought(
            thought_id,
            user_id=self.user_id,
        )
        observed = "\n".join(
            [
                stdout.getvalue(),
                stderr.getvalue(),
                "\n".join(logs.output),
                last_error,
                str(own_api_response),
            ]
        )
        self.assertNotIn(raw_hex, observed)
        self.assertNotIn("raw_transaction", own_api_response)
        self.assertIn("code=-32000", last_error)

    def test_wallet_lease_is_renewed_during_slow_rpc(self):
        thought_id = self.insert_pending()
        chain = FakeChain()
        patches = self.delivery_patches(chain)
        with patches[0], patches[1], patches[2]:
            thought_delivery.prepare_thought(thought_id)

        rpc_started = threading.Event()
        release_rpc = threading.Event()

        def slow_rpc(method, params):
            if method == "eth_getTransactionByHash" and not rpc_started.is_set():
                rpc_started.set()
                release_rpc.wait(timeout=2)
                return None
            return chain.rpc_call(method, params)

        with (
            patch.object(utils, "rpc_call", side_effect=slow_rpc),
            patch.object(thought_delivery, "CLAIM_SECONDS", 0.2),
            patch.object(
                thought_delivery,
                "LEASE_RENEW_INTERVAL_SECONDS",
                0.05,
            ),
        ):
            worker = threading.Thread(
                target=thought_delivery.broadcast_thought,
                args=(thought_id,),
            )
            worker.start()
            self.assertTrue(rpc_started.wait(timeout=1))
            time.sleep(0.35)

            con = connect()
            try:
                with con.cursor() as cur:
                    cur.execute(
                        """
                        SELECT broadcast_claimed_by,
                               broadcast_claim_until > now() AS active
                        FROM ethereum_wallet_state
                        WHERE wallet_address = %s
                        """,
                        (self.wallet.lower(),),
                    )
                    lease = cur.fetchone()
            finally:
                con.close()

            self.assertIsNotNone(lease["broadcast_claimed_by"])
            self.assertTrue(lease["active"])
            self.assertFalse(
                thought_delivery._claim_wallet_broadcast(
                    self.wallet.lower(),
                    0,
                    "competing-owner",
                )
            )

            release_rpc.set()
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())

        self.assertEqual(self.get_delivery_row(thought_id)["status"], "broadcast")
        self.assertEqual(chain.send_calls, 1)

    def test_lost_wallet_owner_cannot_update_thought(self):
        thought_id = self.insert_pending()
        chain = FakeChain()
        patches = self.delivery_patches(chain)
        with patches[0], patches[1], patches[2]:
            thought_delivery.prepare_thought(thought_id)

        thought_claim = thought_delivery._claim(
            thought_id,
            ("prepared",),
        )
        old_owner = "old-owner"
        self.assertTrue(
            thought_delivery._claim_wallet_broadcast(
                self.wallet.lower(),
                0,
                old_owner,
            )
        )

        con = connect()
        try:
            with con:
                with con.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE ethereum_wallet_state
                        SET broadcast_claimed_by = 'new-owner',
                            broadcast_claim_until = now() + interval '1 minute'
                        WHERE wallet_address = %s
                        """,
                        (self.wallet.lower(),),
                    )
        finally:
            con.close()

        self.assertFalse(
            thought_delivery._renew_wallet_broadcast(
                self.wallet.lower(),
                old_owner,
                thought_id,
                thought_claim["claim_id"],
            )
        )
        self.assertFalse(
            thought_delivery._mark_broadcast(
                thought_id,
                thought_claim["claim_id"],
                self.wallet.lower(),
                old_owner,
            )
        )
        thought_delivery._schedule_retry(
            thought_id,
            thought_claim["claim_id"],
            "needs_reconciliation",
            RuntimeError("old worker error"),
            wallet_address=self.wallet.lower(),
            wallet_owner=old_owner,
        )

        row = self.get_delivery_row(thought_id)
        self.assertEqual(row["status"], "prepared")


if __name__ == "__main__":
    unittest.main()
