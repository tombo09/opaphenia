from urllib.parse import quote

from app.config import ETH_CONFIRMATIONS


def owner_delivery_projection(row) -> dict:
    status = row["status"] or "unknown"
    public_ready = row["published_at"] is not None
    username = str(row["username"])
    thought_id = int(row["id"])

    return {
        "id": thought_id,
        "status": status,
        "confirmation_count": int(row["confirmation_count"] or 0),
        "required_confirmations": int(
            row["confirmation_required"] or ETH_CONFIRMATIONS
        ),
        "public_ready": public_ready,
        "public_url": f"/{quote(username, safe='')}/{thought_id}",
        "txid": row["txid"],
        "etherscan_link": row.get("etherscan_link"),
    }
