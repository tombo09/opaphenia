import hashlib
from datetime import datetime, timezone
import requests
import json
from pathlib import Path
import hashlib
import unicodedata
from eth_account import Account
import os
import re
import time
from dataclasses import dataclass


class EthereumConfigurationError(RuntimeError):
    """A safe, user-facing error for unavailable signing configuration."""


@dataclass(frozen=True)
class EthereumSigner:
    account: object
    address: str


def get_ethereum_signer() -> EthereumSigner:
    """Load and validate the Ethereum signer only when signing is required."""
    private_key = os.getenv("ETH_PK")
    if not private_key:
        raise EthereumConfigurationError(
            "Ethereum signing is unavailable: ETH_PK is not configured"
        )
    try:
        account = Account.from_key(private_key)
    except Exception:
        raise EthereumConfigurationError(
            "Ethereum signing is unavailable: ETH_PK is invalid"
        ) from None
    return EthereumSigner(account=account, address=account.address)

# dein Hash als calldata
CALLDATA = "0x149d5ebb64ea3a7239566ff579699045b92d2866b6e6edf256223827f5b2ae7d"
ts1= "0x8df388d1b8ec14a7e186e436ee4b68463ae6dc31f40afb3b9b6ee3244a66a926"

RPC = "https://ethereum-rpc.publicnode.com"


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def to_sqlite_dt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def execute_string(string, username):
    raise RuntimeError("Direct Ethereum sends are disabled; use thought delivery")

version = 1
def with_prefix(text: str, username) -> str:
    prefix = f"v{version}\n@{username}\n\n"
    return prefix + text

def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text

def hash_string(text: str, username) -> str:
    normalized = normalize_text(with_prefix(text, username))
    return "0x" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def get_time(tx_hash, wait=True, timeout=120, poll_interval=3):
    start = time.time()

    while True:
        tx = rpc_call("eth_getTransactionByHash", [tx_hash])

        if tx is not None:
            block_number = tx.get("blockNumber")

            if block_number is not None:
                block = rpc_call("eth_getBlockByNumber", [block_number, False])

                if block is None:
                    raise Exception(f"Block not found: {block_number}")

                block_time = block["timestamp"]
                timestamp = int(block_time, 16)

                return datetime.fromtimestamp(timestamp, tz=timezone.utc)

            if not wait:
                raise Exception(f"Transaction is still pending: {tx_hash}")

        else:
            if not wait:
                raise Exception(f"Transaction not found: {tx_hash}")

        if time.time() - start > timeout:
            raise TimeoutError(f"Transaction not mined within {timeout} seconds: {tx_hash}")

        time.sleep(poll_interval)

def get_input(ts_hash):
    return rpc_call("eth_getTransactionByHash", [ts_hash])["input"]


_LONG_HEX_RE = re.compile(r"0x[0-9a-fA-F]{16,}")


def sanitize_rpc_text(value, sensitive_values=()) -> str:
    text = str(value or "")
    for sensitive in sensitive_values:
        if sensitive:
            text = text.replace(str(sensitive), "[redacted]")
    text = _LONG_HEX_RE.sub("[redacted-hex]", text)
    text = " ".join(text.split())
    return text[:240]


class RPCError(RuntimeError):
    def __init__(self, method, *, http_status=None, code=None, message=None):
        self.method = sanitize_rpc_text(method)
        self.http_status = http_status
        self.code = sanitize_rpc_text(code) if code is not None else None
        self.rpc_message = sanitize_rpc_text(message or "RPC request failed")
        parts = [f"RPC method={self.method}"]
        if self.http_status is not None:
            parts.append(f"http_status={self.http_status}")
        if self.code is not None:
            parts.append(f"code={self.code}")
        parts.append(f"message={self.rpc_message}")
        super().__init__(" ".join(parts))


def _rpc_error_fields(data, params):
    error = data.get("error") if isinstance(data, dict) else None
    if not isinstance(error, dict):
        return None, "RPC request failed"
    return (
        error.get("code"),
        sanitize_rpc_text(error.get("message"), sensitive_values=params),
    )


def rpc_call(method, params):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }

    try:
        r = requests.post(RPC, json=payload, timeout=30)
    except requests.RequestException:
        raise RPCError(method, message="transport failure") from None

    try:
        data = r.json()
    except ValueError:
        data = None

    if not r.ok:
        code, message = _rpc_error_fields(data, params)
        raise RPCError(
            method,
            http_status=r.status_code,
            code=code,
            message=message if data is not None else "non-JSON HTTP error",
        ) from None

    if data is None:
        raise RPCError(
            method,
            http_status=r.status_code,
            message="non-JSON RPC response",
        ) from None

    if "error" in data:
        code, message = _rpc_error_fields(data, params)
        raise RPCError(
            method,
            http_status=r.status_code,
            code=code,
            message=message,
        ) from None

    if "result" not in data:
        raise RPCError(
            method,
            http_status=r.status_code,
            message="RPC response missing result",
        ) from None

    return data["result"]


def execute_ts(hash):
    raise RuntimeError("Direct Ethereum sends are disabled; use thought delivery")



def push_on_chain(hash):
    raise RuntimeError("Direct Ethereum sends are disabled; use thought delivery")


def etherscan_link(txid):
    return f"https://www.etherscan.io/tx/{txid}"
