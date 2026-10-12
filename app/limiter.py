from ipaddress import ip_address

from slowapi import Limiter
from starlette.requests import Request

from app.config import TRUSTED_PROXIES, TRUST_PROXY_HEADERS


def _parse_ip(value: str):
    try:
        return ip_address(value.strip())
    except (AttributeError, ValueError):
        return None


def _is_trusted(address) -> bool:
    return any(address in network for network in TRUSTED_PROXIES)


def get_client_ip(request: Request) -> str:
    peer_host = request.client.host if request.client else None
    peer_ip = _parse_ip(peer_host)
    if not TRUST_PROXY_HEADERS or peer_ip is None or not _is_trusted(peer_ip):
        return peer_host or "unknown"

    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        forwarded = [_parse_ip(item) for item in forwarded_for.split(",")]
        if all(address is not None for address in forwarded):
            chain = [*forwarded, peer_ip]
            for address in reversed(chain):
                if not _is_trusted(address):
                    return str(address)
            return str(chain[0])

    cf_ip = _parse_ip(request.headers.get("CF-Connecting-IP"))
    if cf_ip is not None:
        return str(cf_ip)

    return str(peer_ip)


limiter = Limiter(key_func=get_client_ip)
