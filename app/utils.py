import hashlib
from datetime import datetime, timezone
import requests
import json
from pathlib import Path
import hashlib
import unicodedata
from eth_account import Account
import os
import time

PK = os.getenv("ETH_PK")
if not PK:
    raise RuntimeError("ETH_PK is missing")

acct = Account.from_key(PK)
ADDR = acct.address

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
    content = normalize_text(with_prefix(string, username))
    hashed_content = hash_string(string, username)
    txid = push_on_chain(hashed_content)
    #txid = "0x8df388d1b8ec14a7e186e436ee4b68463ae6dc31f40afb3b9b6ee3244a66a926"
    return content, hashed_content, txid

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


def rpc_call(method, params):
    r = requests.post(RPC, json = {"jsonrpc": "2.0","id": 1,"method": method,"params": params}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data["result"]

def execute_ts(hash):
    # 1) chainId (Mainnet = 1)
    chain_id = int(rpc_call("eth_chainId", []), 16)
    if chain_id != 1:
        raise RuntimeError(f"not Mainnet (chainId={chain_id})")

    # 2) nonce (pending)
    nonce = int(rpc_call("eth_getTransactionCount", [ADDR, "pending"]), 16)

    # 3) Gas-Fees (EIP-1559)
    latest = rpc_call("eth_getBlockByNumber", ["latest", False])
    base_fee = int(latest["baseFeePerGas"], 16)

    prio_hex = rpc_call("eth_maxPriorityFeePerGas", [])
    priority = 5 * 10**6  
    max_fee = base_fee + 2 * priority

    # 4) Gas limit schätzen
    tx_for_estimate = {
        "from": ADDR,
        "to": ADDR,
        "value": hex(0),
        "data": CALLDATA,
        "maxFeePerGas": hex(max_fee),
        "maxPriorityFeePerGas": hex(priority),
    }
    gas = int(rpc_call("eth_estimateGas", [tx_for_estimate]), 16)


    # 5) Type-2 TX bauen und signieren
    tx = {
        "type": 2,
        "chainId": chain_id,
        "nonce": nonce,
        "to": ADDR,
        "value": 0,
        "data": CALLDATA,
        "gas": gas,
        "maxFeePerGas": max_fee,
        "maxPriorityFeePerGas": priority,
    }

    signed = acct.sign_transaction(tx)
    raw = signed.rawTransaction.hex()

    # 6) Broadcast
    tx_hash = rpc_call("eth_sendRawTransaction", ["0x" + raw if not raw.startswith("0x") else raw])
    return ADDR, tx_hash



def push_on_chain(hash):
    # 1) chainId (Mainnet = 1)
    chain_id = int(rpc_call("eth_chainId", []), 16)
    if chain_id != 1:
        raise RuntimeError(f"not Mainnet (chainId={chain_id})")

    # 2) nonce (pending)
    nonce = int(rpc_call("eth_getTransactionCount", [ADDR, "pending"]), 16)

    # 3) Gas-Fees (EIP-1559)
    latest = rpc_call("eth_getBlockByNumber", ["latest", False])
    base_fee = int(latest["baseFeePerGas"], 16)

    prio_hex = rpc_call("eth_maxPriorityFeePerGas", [])
    priority = 2 * 10**8  
    max_fee = base_fee + 2 * priority

    # 4) Gas limit schätzen
    tx_for_estimate = {
        "from": ADDR,
        "to": ADDR,
        "value": hex(0),
        "data": hash,
        "maxFeePerGas": hex(max_fee),
        "maxPriorityFeePerGas": hex(priority),
    }
    gas = int(rpc_call("eth_estimateGas", [tx_for_estimate]), 16)


    # 5) Type-2 TX bauen und signieren
    tx = {
        "type": 2,
        "chainId": chain_id,
        "nonce": nonce,
        "to": ADDR,
        "value": 0,
        "data": hash,
        "gas": gas,
        "maxFeePerGas": max_fee,
        "maxPriorityFeePerGas": priority,
    }

    signed = acct.sign_transaction(tx)
    raw = signed.raw_transaction.hex()

    # 6) Broadcast
    tx_hash = rpc_call("eth_sendRawTransaction", ["0x" + raw if not raw.startswith("0x") else raw])
    return tx_hash


def etherscan_link(txid):
    return f"https://www.etherscan.io/tx/{txid}"

