import httpx
from fastapi import HTTPException, Request

from app.config import TURNSTILE_SECRET_KEY


TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


async def verify_turnstile_token(token: str, request: Request) -> None:
    if not token:
        raise HTTPException(status_code=400, detail="Turnstile token fehlt")

    # IP optional mitsenden. Bei Cloudflare ist CF-Connecting-IP am besten.
    remote_ip = (
        request.headers.get("CF-Connecting-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else None)
    )

    data = {
        "secret": TURNSTILE_SECRET_KEY,
        "response": token,
    }

    if remote_ip:
        data["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(TURNSTILE_VERIFY_URL, data=data)
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPError:
        raise HTTPException(
            status_code=503,
            detail="Turnstile Prüfung aktuell nicht verfügbar"
        )

    if not result.get("success"):
        raise HTTPException(
            status_code=403,
            detail="Turnstile Prüfung fehlgeschlagen"
        )
