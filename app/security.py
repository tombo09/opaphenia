from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, Request
from passlib.context import CryptContext
from jose import jwt, JWTError

from .config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, COOKIE_NAME

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)

def create_access_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user_id(request: Request) -> int:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Nicht eingeloggt")
    try:
        decoded = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = decoded.get("sub")
        if sub is None:
            raise HTTPException(status_code=401, detail="Token ungültig")
        return int(sub)
    except (JWTError, ValueError):
        raise HTTPException(status_code=401, detail="Token ungültig oder abgelaufen")

def is_valid_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        decoded = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = decoded.get("sub")
        return sub is not None
    except (JWTError, ValueError):
        return False
