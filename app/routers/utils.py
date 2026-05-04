


import hashlib
from pathlib import Path

def create_hash(path):
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


import json
from datetime import datetime
from rpc import rpc_call

ts1= "0x8df388d1b8ec14a7e186e436ee4b68463ae6dc31f40afb3b9b6ee3244a66a926"

def get_time(ts_hash):
    block_number = rpc_call("eth_getTransactionByHash", [ts_hash])["blockNumber"]
    block = rpc_call("eth_getBlockByNumber", [block_number, False])
    block_time = block["timestamp"]
    timestamp = int(block_time, 16)
    time = datetime.fromtimestamp(timestamp)
    return time

def get_input(ts_hash):
    return rpc_call("eth_getTransactionByHash", [ts_hash])["input"]


import requests
import json
RPC = "https://ethereum-rpc.publicnode.com"

def rpc_call(method, params):
    r = requests.post(RPC, json = {"jsonrpc": "2.0","id": 1,"method": method,"params": params}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data["result"]






from eth_account import Account
from rpc import rpc_call

RPC = "https://ethereum-rpc.publicnode.com"

PK = open("/home/tom/.eth_pk").read().strip()
acct = Account.from_key(PK)
ADDR = acct.address

# dein Hash als calldata
CALLDATA = "0x149d5ebb64ea3a7239566ff579699045b92d2866b6e6edf256223827f5b2ae7d"

def execute_ts(hash):
    # 1) chainId (Mainnet = 1)
    chain_id = int(rpc_call("eth_chainId", []), 16)
    if chain_id != 1:
        raise RuntimeError(f"Nicht Mainnet (chainId={chain_id})")

    # 2) nonce (pending)
    nonce = int(rpc_call("eth_getTransactionCount", [ADDR, "pending"]), 16)

    # 3) Gas-Fees (EIP-1559)
    latest = rpc_call("eth_getBlockByNumber", ["latest", False])
    base_fee = int(latest["baseFeePerGas"], 16)

    prio_hex = rpc_call("eth_maxPriorityFeePerGas", [])
    priority = 5 * 10**6  # 2 gwei
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



