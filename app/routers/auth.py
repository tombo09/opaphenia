import secrets

from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Response, Form, Request
from fastapi.responses import HTMLResponse

from app.limiter import limiter
from app.turnstile import verify_turnstile_token
from app.rate_limit import assert_rate_limit, normalize_email

from app.config import (
    APP_BASE_URL,
    COOKIE_NAME,
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

router = APIRouter(tags=["auth"])


@router.get("/me")
def me(user_id: int = Depends(get_current_user_id)):
    return {"ok": True, "user_id": user_id}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
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

    # 2. Rate Limit nach E-Mail
    assert_rate_limit(
        scope="signup_email",
        key=email,
        max_events=3,
        window_seconds=60 * 60,
    )

    # 3. Rate Limit nach E-Mail-Domain
    domain = email.split("@")[-1]
    assert_rate_limit(
        scope="signup_domain",
        key=domain,
        max_events=30,
        window_seconds=60 * 60,
    )

    # 4. Turnstile serverseitig prüfen
    await verify_turnstile_token(payload.turnstile_token, request)




    pw_hash = hash_password(payload.password)

    con = connect()
    try:
        with con:
            with con.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (email, username, password_hash, email_verified)
                    VALUES (%s, %s, %s, FALSE)
                    RETURNING id
                    """,
                    (email, username, pw_hash),
                )
                user_id = cur.fetchone()["id"]
    except Exception:
        raise HTTPException(
            status_code=409,
            detail="The email address or username already exists",
        )
    finally:
        con.close()

    token = secrets.token_urlsafe(32)
    token_hash = sha256(token)
    expires = now_utc() + timedelta(minutes=30)

    con = connect()
    try:
        with con:
            with con.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO email_verifications
                    (user_id, purpose, token_hash, expires_at)
                    VALUES (%s, 'signup', %s, %s)
                    """,
                    (user_id, token_hash, expires),
                )
    finally:
        con.close()

    link = f"{APP_BASE_URL}/api/verify-email?token={token}"
    send_email(email, "Verify your email", f"Click to verify: {link}")

    return {"ok": True, "message": "Please check and verify your email address."}


@router.get("/verify-email", response_class=HTMLResponse)
def verify_email(token: str):
    token_hash = sha256(token)

    con = connect()
    try:
        with con.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, purpose, new_email, expires_at, used
                FROM email_verifications
                WHERE token_hash = %s
                """,
                (token_hash,),
            )
            row = cur.fetchone()

            if not row:
                raise HTTPException(status_code=400, detail="Ungültiger Token")

            ver_id = row["id"]
            user_id = row["user_id"]
            purpose = row["purpose"]
            new_email = row["new_email"]
            expires_at = row["expires_at"]
            used = row["used"]

            if used is True:
                return "<h3><This link has already been used./h3>"

            if now_utc() > expires_at:
                return "<h3><The link has expired./h3>"

            if purpose == "signup":
                cur.execute(
                    "UPDATE users SET email_verified = TRUE WHERE id = %s",
                    (user_id,),
                )
            elif purpose == "change_email":
                cur.execute(
                    "UPDATE users SET email = %s, email_verified = TRUE WHERE id = %s",
                    (new_email, user_id),
                )

            cur.execute(
                "UPDATE email_verifications SET used = TRUE WHERE id = %s",
                (ver_id,),
            )
            con.commit()

        return "<h3><Email successfully verified.</h3>"
    finally:
        con.close()

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
                SELECT id, password_hash, email_verified, failed_attempts
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

        token = create_access_token(user_id)
        response.set_cookie(
            key=COOKIE_NAME,
            value=token,
            httponly=True,
            secure=COOKIE_SECURE,
            samesite=COOKIE_SAMESITE,
            max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            path="/",
        )
        return {"ok": True}
    finally:
        con.close()


@router.post("/password-reset/request")
def password_reset_request(payload: ResetRequestIn):
    email = payload.email.strip().lower()

    con = connect()
    try:
        with con.cursor() as cur:
            cur.execute(
                "SELECT id, failed_attempts FROM users WHERE email = %s",
                (email,),
            )
            row = cur.fetchone()

        if not row:
            return {"ok": True}

        user_id = row["id"]
        failed_attempts = row["failed_attempts"]

        if int(failed_attempts or 0) < 5:
            return {"ok": True}

        token = secrets.token_urlsafe(32)
        token_hash = sha256(token)
        expires = now_utc() + timedelta(minutes=30)

        with con:
            with con.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO password_resets (user_id, token_hash, expires_at)
                    VALUES (%s, %s, %s)
                    """,
                    (user_id, token_hash, expires),
                )

        link = f"{APP_BASE_URL}/api/reset-password?token={token}"
        send_email(email, "Reset your password", f"Click to reset: {link}")

        return {"ok": True}
    finally:
        con.close()


@router.get("/reset-password", response_class=HTMLResponse)
def reset_password_page(token: str):
    return f"""
    <h3>Reset password</h3>
    <form method="post" action="/api/password-reset/confirm">
      <input type="hidden" name="token" value="{token}">
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
        with con.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, expires_at, used
                FROM password_resets
                WHERE token_hash = %s
                """,
                (token_hash,),
            )
            row = cur.fetchone()

            if not row:
                return "<h3><Invalid token./h3>"

            reset_id = row["id"]
            user_id = row["user_id"]
            expires_at = row["expires_at"]
            used = row["used"]

            if used is True:
                return "<h3><This link has already been used./h3>"

            if now_utc() > expires_at:
                return "<h3><The link has expired./h3>"

            new_hash = hash_password(new_password)

            cur.execute(
                "UPDATE users SET password_hash = %s, failed_attempts = 0 WHERE id = %s",
                (new_hash, user_id),
            )
            cur.execute(
                "UPDATE password_resets SET used = TRUE WHERE id = %s",
                (reset_id,),
            )
            con.commit()

        return "<h3><Your password has been changed. You can now log in./h3>"
    finally:
        con.close()
