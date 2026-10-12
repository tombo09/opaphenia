from fastapi import APIRouter, Depends, Header, HTTPException, status
from ..db import connect
from ..schemas import ThoughtIn
from ..security import get_current_user_id
from app import utils
from app.moderation import moderate_text
# Kept as a module attribute for compatibility with callers/tests that patch the
# delivery driver. HTTP handlers below deliberately never invoke it.
from app.thought_delivery import process_thought
from app.thought_views import owner_delivery_projection
from app.utils import etherscan_link

router = APIRouter(tags=["thoughts"])

MAX_THOUGHT_LENGTH = 50000
MAX_THOUGHTS_PER_DAY = 18


def _load_thought_identity(user_id: int, idempotency_key: str):
    con = connect()
    try:
        with con.cursor() as cur:
            cur.execute(
                """
                SELECT u.username, t.id, t.hashed_string
                FROM users u
                LEFT JOIN thoughts t
                  ON t.user_id = u.id AND t.idempotency_key = %s
                WHERE u.id = %s
                """,
                (idempotency_key, user_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="User not found")
            return row
    finally:
        con.close()


def _thought_response(thought_id: int):
    con = connect()
    try:
        with con.cursor() as cur:
            cur.execute(
                """
                SELECT t.id, t.status, t.confirmation_count,
                       t.confirmation_required, t.published_at, t.txid,
                       u.username
                FROM thoughts t
                JOIN users u ON u.id = t.user_id
                WHERE t.id = %s
                """,
                (thought_id,),
            )
            row = cur.fetchone()
    finally:
        con.close()

    if not row:
        raise HTTPException(status_code=404, detail="String not found")
    row["etherscan_link"] = etherscan_link(row["txid"]) if row["txid"] else None
    return {"ok": True, **owner_delivery_projection(row)}

@router.post("/thoughts", status_code=status.HTTP_202_ACCEPTED)
def create_thought(
    payload: ThoughtIn,
    user_id: int = Depends(get_current_user_id),
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
):
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="The text is empty")

    if len(content) > MAX_THOUGHT_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"The text must not exceed {MAX_THOUGHT_LENGTH} characters"
        )

    idempotency_key = idempotency_key.strip()
    if not idempotency_key or len(idempotency_key) > 128:
        raise HTTPException(status_code=400, detail="Invalid Idempotency-Key")

    identity = _load_thought_identity(user_id, idempotency_key)
    hashed_string = utils.hash_string(content, identity["username"])
    if identity["id"] is not None:
        if identity["hashed_string"] != hashed_string:
            raise HTTPException(
                status_code=409,
                detail="Idempotency-Key was already used for different content",
            )
        return _thought_response(identity["id"])

    moderation = moderate_text(content)
    if moderation["flagged"]:
        raise HTTPException(
            status_code=400,
            detail="This text could not be saved."
        )

    con = connect()
    try:
        with con.transaction():
            with con.cursor() as cur:
                # This lock covers only the idempotency/quota decision and
                # durable pending insert. No external call occurs here.
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"thought-daily-quota:{user_id}",),
                )
                cur.execute(
                    "SELECT username FROM users WHERE id = %s",
                    (user_id,),
                )
                user = cur.fetchone()
                if not user:
                    raise HTTPException(status_code=404, detail="User not found")

                username = user["username"]
                stored_content = utils.normalize_text(
                    utils.with_prefix(content, username)
                )
                hashed_string = utils.hash_string(content, username)

                cur.execute(
                    """
                    SELECT id, hashed_string
                    FROM thoughts
                    WHERE user_id = %s AND idempotency_key = %s
                    """,
                    (user_id, idempotency_key),
                )
                existing = cur.fetchone()
                if existing:
                    if existing["hashed_string"] != hashed_string:
                        raise HTTPException(
                            status_code=409,
                            detail=(
                                "Idempotency-Key was already used for "
                                "different content"
                            ),
                        )
                    thought_id = existing["id"]
                else:
                    cur.execute(
                        """
                        SELECT COUNT(*) AS cnt
                        FROM thoughts
                        WHERE user_id = %s
                          AND created_at >= date_trunc('day', now())
                          AND created_at < date_trunc('day', now()) + interval '1 day'
                          AND (status IS NULL OR status <> 'failed')
                        """,
                        (user_id,),
                    )
                    count_today = cur.fetchone()["cnt"]

                    if count_today >= MAX_THOUGHTS_PER_DAY:
                        raise HTTPException(
                            status_code=429,
                            detail=(
                                f"A maximum of {MAX_THOUGHTS_PER_DAY} "
                                "strings are allowed per day"
                            ),
                        )

                    cur.execute(
                        """
                        INSERT INTO thoughts
                            (user_id, content, hashed_string, status,
                             idempotency_key, wallet_address)
                        VALUES (%s, %s, %s, 'pending', %s, %s)
                        ON CONFLICT (user_id, idempotency_key)
                            WHERE idempotency_key IS NOT NULL
                        DO NOTHING
                        RETURNING id
                        """,
                        (
                            user_id,
                            stored_content,
                            hashed_string,
                            idempotency_key,
                            None,
                        ),
                    )
                    inserted = cur.fetchone()
                    if inserted:
                        thought_id = inserted["id"]
                    else:
                        cur.execute(
                            """
                            SELECT id, hashed_string
                            FROM thoughts
                            WHERE user_id = %s AND idempotency_key = %s
                            """,
                            (user_id, idempotency_key),
                        )
                        winner = cur.fetchone()
                        if not winner or winner["hashed_string"] != hashed_string:
                            raise HTTPException(
                                status_code=409,
                                detail=(
                                    "Idempotency-Key was already used for "
                                    "different content"
                                ),
                            )
                        thought_id = winner["id"]

    finally:
        con.close()

    return _thought_response(thought_id)

@router.get("/thoughts")
def list_thoughts(user_id: int = Depends(get_current_user_id)):
    con = connect()
    try:
        with con.cursor() as cur:
            cur.execute(
                """
                SELECT t.id, t.content, t.created_at, t.status,
                       t.confirmation_count, t.confirmation_required,
                       t.published_at, t.txid, u.username
                FROM thoughts t
                JOIN users u ON u.id = t.user_id
                WHERE t.user_id = %s
                ORDER BY t.created_at DESC
                """,
                (user_id,),
            )
            rows = cur.fetchall()
    finally:
        con.close()

    items = []
    for row in rows:
        row["etherscan_link"] = (
            etherscan_link(row["txid"]) if row["txid"] else None
        )
        items.append(
            {
                "content": row["content"],
                "created_at": row["created_at"],
                **owner_delivery_projection(row),
            }
        )
    return {"ok": True, "items": items}
