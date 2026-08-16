import os
from decimal import Decimal

from fastapi import APIRouter, HTTPException

from app.utils import rpc_call


router = APIRouter(tags=["eth"])


ETH_WALLET_ADDRESS = os.getenv("ETH_WALLET_ADDRESS")

MAX_STRING_FEE_ETH = Decimal(
    os.getenv("MAX_STRING_FEE_ETH", "0.00005")
)


@router.get("/eth/status")
def eth_status():

    if not ETH_WALLET_ADDRESS:
        raise HTTPException(
            status_code=500,
            detail="ETH_WALLET_ADDRESS missing",
        )

    try:
        balance_hex = rpc_call(
            "eth_getBalance",
            [
                ETH_WALLET_ADDRESS,
                "latest",
            ],
        )

        balance_wei = int(balance_hex, 16)

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not query Ethereum balance",
        ) from exc

    balance_eth = (
        Decimal(balance_wei)
        / Decimal(10**18)
    )

    max_fee_wei = int(
        MAX_STRING_FEE_ETH
        * Decimal(10**18)
    )

    possible_strings = (
        balance_wei // max_fee_wei
        if max_fee_wei > 0
        else 0
    )

    return {
    "wallet_address": ETH_WALLET_ADDRESS,
        "balance_eth": str(balance_eth),
        "possible_strings": possible_strings,
    }
