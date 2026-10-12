import secrets
import logging
from html import escape

from psycopg.errors import UniqueViolation

from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Response, Form, Request
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from app.limiter import limiter
from app.limiter import get_client_ip
from app.turnstile import verify_turnstile_token
from app.rate_limit import assert_rate_limit, normalize_email, assert_global_daily_signup_limit

from app.config import (
    APP_BASE_URL,
    COOKIE_NAME,
    COOKIE_HTTPONLY,
    COOKIE_PATH,
    COOKIE_SECURE,
    COOKIE_SAMESITE,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)
from app.db import connect
from app.schemas import LoginIn, SignupIn, ResetRequestIn
from app.security import (
    create_access_token,
    verify_password,
    hash_password,
    get_current_user_id,
)
from app.utils import sha256, now_utc
from app.email_utils import send_email
from app.email_outbox import enqueue_email

router = APIRouter(tags=["auth"])
logger = logging.getLogger(__name__)

PASSWORD_RESET_RATE_WINDOW_SECONDS = 60 * 60
PASSWORD_RESET_EMAIL_MAX = 3
PASSWORD_RESET_IP_MAX = 10


def _persist_signup(email, username, password_hash, token_hash, expires, link):
    con = connect()
    try:
        with con.transaction():
            with con.cursor() as cur:
                quota_date = assert_global_daily_signup_limit(cur)
                cur.execute(
                    """
                    INSERT INTO users (email, username, password_hash, email_verified)
                    VALUES (%s, %s, %s, FALSE)
                    RETURNING id
                    """,
                    (email, username, password_hash),
                )
                user_id = cur.fetchone()["id"]
                cur.execute(
                    """
                    INSERT INTO email_verifications
                    (user_id, purpose, token_hash, expires_at)
                    VALUES (%s, 'signup', %s, %s)
                    """,
                    (user_id, token_hash, expires),
                )
                cur.execute(
                    """
                    INSERT INTO signup_quota_allocations
                        (user_id, quota_date)
                    VALUES (%s, %s)
                    """,
                    (user_id, quota_date),
                )
                enqueue_email(
                    cur,
                    user_id=user_id,
                    kind="signup_verification",
                    to_email=email,
                    subject="Verify your email",
                    body=f"Click to verify: {link}",
                )
    finally:
        con.close()


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=COOKIE_HTTPONLY,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path=COOKIE_PATH,
    )


def _clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        path=COOKIE_PATH,
        secure=COOKIE_SECURE,
        httponly=COOKIE_HTTPONLY,
        samesite=COOKIE_SAMESITE,
    )


@router.get("/me")
def me(user_id: int = Depends(get_current_user_id)):
    return {"ok": True, "user_id": user_id}


@router.post("/logout")
def logout(response: Response):
    _clear_auth_cookie(response)
    return {"ok": True}



@router.post("/signup")
@limiter.limit("5/minute")
async def signup(request:Request, payload: SignupIn):
    # 1. Honeypot: normale Nutzer füllen das nicht aus
    if payload.website:
        raise HTTPException(status_code=400, detail="Ungültige Anfrage")
    
    email = normalize_email(payload.email)
    username = payload.username.strip()

    if not username:
        raise HTTPException(status_code=400, detail="A username is required")
    if len(payload.password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Password is too short (min. 8 characters)",
        )

    # 2. Rate Limit nach E-Mail
    await run_in_threadpool(
        assert_rate_limit,
        "signup_email",
        email,
        3,
        60 * 60,
    )

    # 3. Rate Limit nach E-Mail-Domain
    domain = email.split("@")[-1]
    await run_in_threadpool(
        assert_rate_limit,
        "signup_domain",
        domain,
        30,
        60 * 60,
    )

    # 4. Turnstile serverseitig prüfen
    await verify_turnstile_token(payload.turnstile_token, request)

    pw_hash = await run_in_threadpool(hash_password, payload.password)
    token = secrets.token_urlsafe(32)
    token_hash = sha256(token)
    expires = now_utc() + timedelta(minutes=30)
    link = f"{APP_BASE_URL}/api/verify-email?token={token}"

    try:
        await run_in_threadpool(
            _persist_signup,
            email,
            username,
            pw_hash,
            token_hash,
            expires,
            link,
        )
    except UniqueViolation:
        raise HTTPException(
            status_code=409,
            detail="The email address or username already exists",
        )
    return {"ok": True, "message": "Please check and verify your email address."}


@router.get("/verify-email", response_class=HTMLResponse)
def verify_email(token: str):
    token_hash = sha256(token)
    old_email_to_notify = None
    changed_user_id = None

    con = connect()
    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    """
                    SELECT user_id
                    FROM email_verifications
                    WHERE token_hash = %s
                    """,
                    (token_hash,),
                )
                token_owner = cur.fetchone()
                if not token_owner:
                    raise HTTPException(
                        status_code=400,
                        detail="Ungültiger Token",
                    )

                cur.execute(
                    "SELECT email FROM users WHERE id = %s FOR UPDATE",
                    (token_owner["user_id"],),
                )
                user = cur.fetchone()
                if not user:
                    raise HTTPException(status_code=400, detail="Ungültiger Token")

                cur.execute(
                    """
                    UPDATE email_verifications
                    SET used = TRUE
                    WHERE token_hash = %s
                      AND used = FALSE
                      AND expires_at > now()
                    RETURNING user_id, purpose, new_email
                    """,
                    (token_hash,),
                )
                row = cur.fetchone()
                if not row:
                    cur.execute(
                        """
                        SELECT used, expires_at <= now() AS expired
                        FROM email_verifications
                        WHERE token_hash = %s
                        """,
                        (token_hash,),
                    )
                    unavailable = cur.fetchone()
                    if unavailable["used"]:
                        return "<h3>This link has already been used.</h3>"
                    return "<h3>The link has expired.</h3>"

                if row["purpose"] == "signup":
                    cur.execute(
                        "UPDATE users SET email_verified = TRUE WHERE id = %s",
                        (row["user_id"],),
                    )
                elif row["purpose"] == "change_email":
                    old_email_to_notify = user["email"]
                    changed_user_id = row["user_id"]
                    cur.execute(
                        """
                        UPDATE users
                        SET email = %s, email_verified = TRUE,
                            auth_version = auth_version + 1
                        WHERE id = %s
                        """,
                        (row["new_email"], row["user_id"]),
                    )
    except UniqueViolation:
        raise HTTPException(
            status_code=409,
            detail="This email address already exists",
        )
    finally:
        con.close()

    if old_email_to_notify:
        try:
            send_email(
                old_email_to_notify,
                "Your email address was changed",
                (
                    "The email address on your account was changed. "
                    "If you did not make this change, contact support immediately."
                ),
            )
        except Exception:
            logger.exception(
                "Could not send email-change security notification: user_id=%s",
                changed_user_id,
            )

    return "<h3>Email successfully verified.</h3>"

@router.post("/login")
@limiter.limit("10/minute")
def login(request: Request, data: LoginIn, response: Response):
    login_value = data.login.strip()
    login_value_lower = login_value.lower()

    assert_rate_limit(
        scope="login_user",
        key=login_value_lower,
        max_events=10,
        window_seconds=10 * 60,
    )

    con = connect()
    try:
        with con.cursor() as cur:
            cur.execute(
                """
                SELECT id, password_hash, email_verified, failed_attempts,
                       auth_version
                FROM users
                WHERE lower(email) = %s OR lower(username) = %s
                """,
                (login_value_lower, login_value_lower),
            )
            row = cur.fetchone()

            if not row:
                raise HTTPException(status_code=401, detail="Incorrect login details")

            user_id = row["id"]
            pw_hash = row["password_hash"]
            email_verified = row["email_verified"]
            failed_attempts = row["failed_attempts"] or 0
            auth_version = row["auth_version"]

            if email_verified is not True:
                raise HTTPException(
                    status_code=403,
                    detail="Please verify your email address first",
                )

            if not verify_password(data.password, pw_hash):
                failed_attempts += 1
                cur.execute(
                    "UPDATE users SET failed_attempts = %s WHERE id = %s",
                    (failed_attempts, user_id),
                )
                con.commit()

                if failed_attempts >= 5:
                    raise HTTPException(
                        status_code=423,
                        detail="Too many failed attempts. Please reset your password.",
                    )

                raise HTTPException(status_code=401, detail="Incorrect login details")

            cur.execute(
                "UPDATE users SET failed_attempts = 0 WHERE id = %s",
                (user_id,),
            )
            con.commit()

        token = create_access_token(user_id, auth_version)
        _set_auth_cookie(response, token)
        return {"ok": True}
    finally:
        con.close()


@router.post("/password-reset/request")
def password_reset_request(request: Request, payload: ResetRequestIn):
    email = normalize_email(payload.email)
    try:
        assert_rate_limit(
            scope="password_reset_email",
            key=email,
            max_events=PASSWORD_RESET_EMAIL_MAX,
            window_seconds=PASSWORD_RESET_RATE_WINDOW_SECONDS,
        )
        assert_rate_limit(
            scope="password_reset_ip",
            key=get_client_ip(request),
            max_events=PASSWORD_RESET_IP_MAX,
            window_seconds=PASSWORD_RESET_RATE_WINDOW_SECONDS,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(
            "Operational failure: operation=password_reset_request "
            "stage=rate_limit error=%s",
            type(exc).__name__,
        )
        return {"ok": True}

    con = None
    try:
        con = connect()
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, failed_attempts
                    FROM users
                    WHERE lower(email) = %s
                    """,
                    (email,),
                )
                row = cur.fetchone()
                if not row or int(row["failed_attempts"] or 0) < 5:
                    return {"ok": True}

                user_id = row["id"]
                token = secrets.token_urlsafe(32)
                token_hash = sha256(token)
                expires = now_utc() + timedelta(minutes=30)
                link = f"{APP_BASE_URL}/api/reset-password?token={token}"
                cur.execute(
                    """
                    SELECT pg_advisory_xact_lock(
                        hashtextextended(
                            'password-reset-user:' || %s::text,
                            0
                        )
                    )
                    """,
                    (user_id,),
                )
                cur.execute(
                    """
                    UPDATE password_resets
                    SET used = TRUE
                    WHERE user_id = %s AND used = FALSE
                    """,
                    (user_id,),
                )
                cur.execute(
                    """
                    INSERT INTO password_resets (user_id, token_hash, expires_at)
                    VALUES (%s, %s, %s)
                    """,
                    (user_id, token_hash, expires),
                )
                send_email(
                    email,
                    "Reset your password",
                    f"Click to reset: {link}",
                )
    except Exception as exc:
        logger.warning(
            "Operational failure: operation=password_reset_request "
            "stage=create_reset error=%s",
            type(exc).__name__,
        )
        return {"ok": True}
    finally:
        if con is not None:
            con.close()
    return {"ok": True}


@router.get("/reset-password", response_class=HTMLResponse)
def reset_password_page(token: str):
    escaped_token = escape(token, quote=True)
    return f"""
    <h3>Reset password</h3>
    <form method="post" action="/api/password-reset/confirm">
      <input type="hidden" name="token" value="{escaped_token}">
      <input name="new_password" type="password" placeholder="new password" required><br><br>
      <input name="new_password2" type="password" placeholder="repeat new password" required><br><br>
      <button type="submit">Set new password</button>
    </form>
    """


@router.post("/password-reset/confirm", response_class=HTMLResponse)
def password_reset_confirm(
    token: str = Form(...),
    new_password: str = Form(...),
    new_password2: str = Form(...),
):
    if new_password != new_password2:
        return "<h3><The passwords do not match./h3>"
    if len(new_password) < 8:
        return "<h3><Password too short (min. 8 characters)./h3>"

    token_hash = sha256(token)

    con = connect()
    try:
        new_hash = hash_password(new_password)
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    """
                    UPDATE password_resets
                    SET used = TRUE
                    WHERE token_hash = %s
                      AND used = FALSE
                      AND expires_at > now()
                    RETURNING user_id
                    """,
                    (token_hash,),
                )
                row = cur.fetchone()
                if not row:
                    cur.execute(
                        """
                        SELECT used, expires_at <= now() AS expired
                        FROM password_resets
                        WHERE token_hash = %s
                        """,
                        (token_hash,),
                    )
                    unavailable = cur.fetchone()
                    if not unavailable:
                        return "<h3><Invalid token./h3>"
                    if unavailable["used"]:
                        return "<h3><This link has already been used./h3>"
                    return "<h3><The link has expired./h3>"

                cur.execute(
                    """
                    UPDATE users
                    SET password_hash = %s, failed_attempts = 0,
                        auth_version = auth_version + 1
                    WHERE id = %s
                    """,
                    (new_hash, row["user_id"]),
                )

        return "<h3><Your password has been changed. You can now log in./h3>"
    finally:
        con.close()
