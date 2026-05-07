from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def get_client_ip(request: Request) -> str:
    # Wenn du wirklich hinter Cloudflare bist:
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip

    # Wenn du hinter Nginx bist:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    return get_remote_address(request)


limiter = Limiter(key_func=get_client_ip)
