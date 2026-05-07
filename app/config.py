import os

DATABASE_URL = os.getenv("DATABASE_URL")

# Für Links in Emails (später https://deinedomain.tld)
APP_BASE_URL = "https://opaphenia.com"

TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY")

# JWT
SECRET_KEY = os.getenv("SECRET_KEY", "CHANGE_ME_IN_PROD")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
COOKIE_NAME = os.getenv("COOKIE_NAME", "access_token")

# Cookies (Server/HTTPS: COOKIE_SECURE=1)
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")  # ggf. "none" + secure=True bei cross-domain

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
