import sqlite3
from fastapi import APIRouter, Depends, HTTPException
from ..db import connect
from ..schemas import EmailUpdateIn, PasswordUpdate, VisibilityUpdate, TimezoneIn
from ..security import get_current_user_id, verify_password, hash_password
from ..utils import sha256, now_utc
from ..email_utils import send_email
from ..config import APP_BASE_URL
import secrets
from datetime import timedelta
from fastapi.responses import JSONResponse
import json
from fastapi import Response

router = APIRouter(tags=["account"])

@router.get("/account")
def get_account(user_id: int = Depends(get_current_user_id)):
    con = connect()
    cur = con.cursor()
    cur.execute(
        "SELECT email, username, strings_public, timezone FROM users WHERE id = %s",
        (user_id,)
    )
    row = cur.fetchone()
    con.close()

    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "ok": True,
        "user_id": user_id,
        "email": row["email"],
        "username": row["username"],
        "strings_public": bool(row["strings_public"]),
        "timezone": row["timezone"],
    }

@router.put("/account/request-email-change")
def request_email_change(payload: EmailUpdateIn, user_id: int = Depends(get_current_user_id)):
    new_email = payload.email.strip().lower()

    token = secrets.token_urlsafe(32)
    token_hash = sha256(token)
    expires = now_utc() + timedelta(minutes=30)

    con = connect()
    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    """
                    SELECT password_hash
                    FROM users
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (user_id,),
                )
                user = cur.fetchone()
                if not user:
                    raise HTTPException(status_code=404, detail="User not found")

                if not verify_password(
                    payload.current_password,
                    user["password_hash"],
                ):
                    raise HTTPException(
                        status_code=401,
                        detail="The current password is incorrect",
                    )

                cur.execute(
                    "SELECT 1 FROM users WHERE lower(email) = %s",
                    (new_email,),
                )
                if cur.fetchone():
                    raise HTTPException(
                        status_code=409,
                        detail="This email address already exists",
                    )

                cur.execute(
                    """
                    UPDATE email_verifications
                    SET used = TRUE
                    WHERE user_id = %s
                      AND purpose = 'change_email'
                      AND used = FALSE
                    """,
                    (user_id,),
                )
                cur.execute(
                    """
                    INSERT INTO email_verifications
                        (user_id, purpose, new_email, token_hash, expires_at)
                    VALUES (%s, 'change_email', %s, %s, %s)
                    """,
                    (user_id, new_email, token_hash, expires),
                )
    finally:
        con.close()

    link = f"{APP_BASE_URL}/api/verify-email?token={token}"
    send_email(new_email, "Confirm your new email", f"Click to confirm: {link}")

    return {"ok": True, "message": "A confirmation link has been sent to your new email address."}

@router.put("/account/password")
def update_password(payload: PasswordUpdate, user_id: int = Depends(get_current_user_id)):
    if payload.new_password != payload.new_password2:
        raise HTTPException(status_code=400, detail="New passwords do not match")
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password is too short (min. 8 characters)")

    con = connect()
    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    "SELECT password_hash FROM users WHERE id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="User not found")

                if not verify_password(
                    payload.old_password,
                    row["password_hash"],
                ):
                    raise HTTPException(
                        status_code=401,
                        detail="The old password is incorrect",
                    )

                new_hash = hash_password(payload.new_password)
                cur.execute(
                    """
                    UPDATE users
                    SET password_hash = %s,
                        auth_version = auth_version + 1
                    WHERE id = %s
                    """,
                    (new_hash, user_id),
                )
    finally:
        con.close()
    return {"ok": True}

@router.put("/account/visibility")
def update_visibility(payload: VisibilityUpdate, user_id: int = Depends(get_current_user_id)):
    con = connect()
    cur = con.cursor()
    cur.execute("UPDATE users SET strings_public = %s WHERE id = %s", (True if payload.strings_public else False, user_id))
    con.commit()
    con.close()
    return {"ok": True, "strings_public": payload.strings_public}


@router.post("/account/timezone")
def save_account_timezone(payload: TimezoneIn, user_id: int = Depends(get_current_user_id)):
    timezone = (payload.timezone or "").strip()

    if not timezone:
        raise HTTPException(status_code=400, detail="Time zone missing")

    con = connect()
    try:
        with con.cursor() as cur:
            cur.execute(
                "UPDATE users SET timezone = %s WHERE id = %s",
                (timezone, user_id),
            )
        con.commit()
        return {"ok": True, "timezone": timezone}
    finally:
        con.close()


@router.get("/account/export")
def export_account_strings(user_id: int = Depends(get_current_user_id)):
    con = connect()
    cur = con.cursor()

    cur.execute(
        """
        SELECT
            id,
            content,
            created_at,
            blocktime,
            hashed_string,
            txid
        FROM thoughts
        WHERE user_id = %s
        ORDER BY created_at DESC
        """,
        (user_id,)
    )

    rows = cur.fetchall()
    con.close()

    data = {
        "version": 1,
        "count": len(rows),
        "strings": [
            {
                "id": row["id"],
                "content": row["content"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "blocktime": row["blocktime"].isoformat() if hasattr(row["blocktime"], "isoformat") else row["blocktime"],
                "hash": row["hashed_string"],
                "txid": row["txid"],
            }
            for row in rows
        ],
    }

    json_text = json.dumps(
        data,
        ensure_ascii=False,
        indent=2
    )

    return Response(
        content=json_text,
        media_type="application/json",
        headers={
            "Content-Disposition": "attachment; filename=strings-export.json"
        }
    )
