from fastapi import APIRouter, Depends, HTTPException
from ..db import connect
from ..schemas import ThoughtIn
from ..security import get_current_user_id
from app.utils import get_time, execute_string
from app.moderation import moderate_text

router = APIRouter(tags=["thoughts"])

MAX_THOUGHT_LENGTH = 500
MAX_THOUGHTS_PER_DAY = 80

@router.post("/thoughts")
def create_thought(payload: ThoughtIn, user_id: int = Depends(get_current_user_id)):
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Text ist leer")

    if len(content) > MAX_THOUGHT_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Text darf maximal {MAX_THOUGHT_LENGTH} Zeichen haben"
        )
    
    moderation = moderate_text(content)
    if moderation["flagged"]:
        raise HTTPException(
            status_code=400,
            detail="Dieser Text konnte nicht gespeichert werden."
        )

    con = connect()
    try:
        with con.cursor() as cur:
            cur.execute("SELECT username FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="User nicht gefunden")

            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM thoughts
                WHERE user_id = %s
                  AND created_at >= date_trunc('day', now())
                  AND created_at < date_trunc('day', now()) + interval '1 day'
                """,
                (user_id,)
            )
            count_today = cur.fetchone()["cnt"]

            if count_today >= MAX_THOUGHTS_PER_DAY:
                raise HTTPException(
                    status_code=429,
                    detail=f"Maximal {MAX_THOUGHTS_PER_DAY} Strings pro Tag erlaubt"
                )

            username = row["username"]
            content, hashed_string, txid = execute_string(content, username)
            blocktime = get_time(txid)

            cur.execute(
                """
                INSERT INTO thoughts (user_id, content, blocktime, hashed_string, txid)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (user_id, content, blocktime, hashed_string, txid)
            )
            new_id = cur.fetchone()["id"]

        con.commit()
        return {"ok": True, "id": new_id}

    finally:
        con.close()

@router.get("/thoughts")
def list_thoughts(user_id: int = Depends(get_current_user_id)):
    con = connect()
    cur = con.cursor()
    cur.execute(
    "SELECT id, content, created_at FROM thoughts WHERE user_id = %s ORDER BY created_at DESC",
    (user_id,)
    )
    rows = cur.fetchall()
    con.close()

    return {"ok": True, "items": [{"id": r["id"], "content": r["content"], "created_at": r["created_at"]} for r in rows]}
