from fastapi import APIRouter, Depends, HTTPException
from app.db import connect
from app.utils import etherscan_link
from app.security import get_current_user_id

router = APIRouter(tags=["public"])


@router.get("/public/search")
def public_search(q: str):
    q = (q or "").strip().lower()
    if len(q) < 1:
        return {"ok": True, "items": []}

    con = connect()
    try:
        with con.cursor() as cur:
            cur.execute(
                """
                SELECT id, username
                FROM users
                WHERE strings_public = TRUE
                  AND lower(username) LIKE %s
                ORDER BY username
                LIMIT 20
                """,
                (f"%{q}%",),
            )
            rows = cur.fetchall()

        return {
            "ok": True,
            "items": [{"id": r["id"], "username": r["username"]} for r in rows],
        }
    finally:
        con.close()




@router.get("/public/thoughts/by-user/{user_id}")
def public_thoughts_by_user(user_id: int):
    con = connect()
    try:
        with con.cursor() as cur:
            cur.execute("SELECT strings_public, username FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()

            if not row:
                raise HTTPException(status_code=404, detail="User not found")

            if row["strings_public"] is not True:
                raise HTTPException(status_code=403, detail="This account is private")

            cur.execute(
                """
                SELECT id, content, created_at
                FROM thoughts
                WHERE user_id = %s
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
            items = [
                {
                    "id": r["id"],
                    "content": r["content"],
                    "created_at": r["created_at"],
                }
                for r in cur.fetchall()
            ]

        return {
            "ok": True,
            "user": {"id": user_id, "username": row["username"]},
            "items": items,
        }
    finally:
        con.close()


@router.get("/public/thoughts/{thought_id}")
def get_public_thought(thought_id: int):
    con = connect()
    try:
        with con.cursor() as cur:
            cur.execute(
                """
                SELECT
                    t.id,
                    t.content,
                    t.created_at,
                    t.blocktime,
                    t.hashed_string,
                    t.txid,
                    u.id AS user_id,
                    u.username,
                    u.strings_public
                FROM thoughts t
                JOIN users u ON u.id = t.user_id
                WHERE t.id = %s
                """,
                (thought_id,),
            )
            row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="String not found")

        if row["strings_public"] is not True:
            raise HTTPException(status_code=403, detail="This string is not public")

        link = etherscan_link(row["txid"]) if row["txid"] else None

        return {
            "id": row["id"],
            "content": row["content"],
            "created_at": row["created_at"],
            "blocktime": row["blocktime"],
            "hashed_string": row["hashed_string"],
            "txid": row["txid"],
            "etherscan_link": link,
            "user": {
                "id": row["user_id"],
                "username": row["username"],
            },
        }
    finally:
        con.close()



@router.get("/public/user/{username}")
def public_user_by_username(username: str):
    username = (username or "").strip().lower()

    con = connect()
    try:
        with con.cursor() as cur:
            cur.execute(
                """
                SELECT id, username, strings_public
                FROM users
                WHERE lower(username) = %s
                """,
                (username,),
            )
            user = cur.fetchone()

            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            if user["strings_public"] is not True:
                raise HTTPException(status_code=403, detail="This account is private")

            cur.execute(
                """
                SELECT id, content, created_at
                FROM thoughts
                WHERE user_id = %s
                ORDER BY created_at DESC
                """,
                (user["id"],),
            )
            items = [
                {
                    "id": r["id"],
                    "content": r["content"],
                    "created_at": r["created_at"],
                }
                for r in cur.fetchall()
            ]

        return {
            "ok": True,
            "user": {
                "id": user["id"],
                "username": user["username"],
            },
            "items": items,
        }
    finally:
        con.close()



@router.get("/public/user/{username}/thoughts/{thought_id}")
def public_thought_by_username(username: str, thought_id: int):
    username = (username or "").strip().lower()

    con = connect()
    try:
        with con.cursor() as cur:
            cur.execute(
                """
                SELECT
                    t.id,
                    t.content,
                    t.created_at,
                    t.blocktime,
                    t.hashed_string,
                    t.txid,
                    u.username,
                    u.strings_public
                FROM thoughts t
                JOIN users u ON u.id = t.user_id
                WHERE lower(u.username) = %s
                  AND t.id = %s
                """,
                (username, thought_id),
            )
            row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="String not found")

        if row["strings_public"] is not True:
            raise HTTPException(status_code=403, detail="This account is private")

        link = etherscan_link(row["txid"]) if row["txid"] else None

        return {
            "id": row["id"],
            "username": row["username"],
            "content": row["content"],
            "created_at": row["created_at"],
            "blocktime": row["blocktime"],
            "hashed_string": row["hashed_string"],
            "txid": row["txid"],
            "etherscan_link": link,
        }
    finally:
        con.close()


@router.get("/thoughts/{thought_id}")
def get_own_thought(thought_id: int, user_id: int = Depends(get_current_user_id)):
    con = connect()
    try:
        with con.cursor() as cur:
            cur.execute(
                """
                SELECT
                    t.id,
                    t.content,
                    t.created_at,
                    t.blocktime,
                    t.hashed_string,
                    t.txid,
                    u.username
                FROM thoughts t
                JOIN users u ON u.id = t.user_id
                WHERE t.id = %s
                  AND t.user_id = %s
                """,
                (thought_id, user_id),
            )
            row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="String not found")

        link = etherscan_link(row["txid"]) if row["txid"] else None

        return {
            "id": row["id"],
            "username": row["username"],
            "content": row["content"],
            "created_at": row["created_at"],
            "blocktime": row["blocktime"],
            "hashed_string": row["hashed_string"],
            "txid": row["txid"],
            "etherscan_link": link,
        }
    finally:
        con.close()
