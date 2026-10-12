import os
from ipaddress import IPv4Network, IPv6Network, ip_network


class ConfigurationError(RuntimeError):
    pass


def _environment() -> str:
    value = os.getenv("APP_ENV", "development").strip().lower()
    if value not in {"development", "test", "production"}:
        raise ConfigurationError(
            "APP_ENV must be development, test, or production"
        )
    return value


def _boolean(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be a boolean value")


def _positive_integer(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        raise ConfigurationError(f"{name} must be a positive integer") from None
    if value < 1:
        raise ConfigurationError(f"{name} must be a positive integer")
    return value


def _trusted_proxies() -> tuple[IPv4Network | IPv6Network, ...]:
    configured = os.getenv("TRUSTED_PROXIES", "").strip()
    if not configured:
        if TRUST_PROXY_HEADERS:
            raise ConfigurationError(
                "TRUSTED_PROXIES is required when TRUST_PROXY_HEADERS is enabled"
            )
        return ()

    networks = []
    for item in configured.split(","):
        value = item.strip()
        if not value:
            raise ConfigurationError("TRUSTED_PROXIES contains an empty entry")
        try:
            networks.append(ip_network(value, strict=False))
        except ValueError:
            raise ConfigurationError(
                f"TRUSTED_PROXIES contains an invalid IP address or network: {value}"
            ) from None
    return tuple(networks)


APP_ENV = _environment()
IS_PRODUCTION = APP_ENV == "production"

DATABASE_URL = os.getenv("DATABASE_URL")

# Für Links in Emails (später https://deinedomain.tld)
APP_BASE_URL = "https://opaphenia.com"

TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY")
TRUST_PROXY_HEADERS = _boolean("TRUST_PROXY_HEADERS", False)
TRUSTED_PROXIES = _trusted_proxies()
ETH_CONFIRMATIONS = _positive_integer("ETH_CONFIRMATIONS", 12)

# JWT
_DEVELOPMENT_SECRET = "development-only-jwt-secret-not-for-production"
_INSECURE_SECRETS = {
    "CHANGE_ME_IN_PROD",
    "change-me",
    "changeme",
    "secret",
    _DEVELOPMENT_SECRET,
}


def _jwt_secret() -> str:
    value = os.getenv("SECRET_KEY")
    if value is None and not IS_PRODUCTION:
        return _DEVELOPMENT_SECRET
    if not value:
        raise ConfigurationError("SECRET_KEY is required in production")
    if IS_PRODUCTION and (
        value in _INSECURE_SECRETS
        or len(value) < 32
        or len(set(value)) < 4
    ):
        raise ConfigurationError(
            "SECRET_KEY is insecure; configure a strong secret of at least 32 characters"
        )
    return value


SECRET_KEY = _jwt_secret()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
COOKIE_NAME = os.getenv("COOKIE_NAME", "access_token")

COOKIE_HTTPONLY = True
COOKIE_PATH = "/"
COOKIE_SECURE = _boolean("COOKIE_SECURE", IS_PRODUCTION)
if IS_PRODUCTION and not COOKIE_SECURE:
    raise ConfigurationError("COOKIE_SECURE must be enabled in production")

COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax").strip().lower()
if COOKIE_SAMESITE not in {"lax", "strict", "none"}:
    raise ConfigurationError("COOKIE_SAMESITE must be lax, strict, or none")
if COOKIE_SAMESITE == "none" and not COOKIE_SECURE:
    raise ConfigurationError("COOKIE_SAMESITE=none requires COOKIE_SECURE=true")

# CORS
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://127.0.0.1:5500,http://localhost:5500,http://127.0.0.1:8000,http://localhost:8000"
).split(",")

# SMTP (Porkbun)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.porkbun.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
