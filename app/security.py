from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, Request
from passlib.context import CryptContext
from jose import jwt, JWTError

from .config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, COOKIE_NAME
from .db import connect

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)

def create_access_token(user_id: int, auth_version: int) -> str:
    payload = {
        "sub": str(user_id),
        "av": auth_version,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _token_identity(token: str) -> tuple[int, int]:
    decoded = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    sub = decoded.get("sub")
    auth_version = decoded.get("av")
    if sub is None or isinstance(auth_version, bool) or not isinstance(auth_version, int):
        raise JWTError("Token identity claims are invalid")
    return int(sub), auth_version


def _auth_version_matches(user_id: int, token_auth_version: int) -> bool:
    con = connect()
    try:
        with con.cursor() as cur:
            cur.execute(
                "SELECT auth_version FROM users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            return bool(row and row["auth_version"] == token_auth_version)
    finally:
        con.close()

def get_current_user_id(request: Request) -> int:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Nicht eingeloggt")
    try:
        user_id, auth_version = _token_identity(token)
    except (JWTError, ValueError):
        raise HTTPException(status_code=401, detail="Token ungültig oder abgelaufen")
    if not _auth_version_matches(user_id, auth_version):
        raise HTTPException(status_code=401, detail="Token ungültig oder abgelaufen")
    return user_id

def is_valid_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        user_id, auth_version = _token_identity(token)
        return _auth_version_matches(user_id, auth_version)
    except (JWTError, ValueError):
        return False
