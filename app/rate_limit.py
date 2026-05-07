from fastapi import HTTPException

from app.db import connect


def normalize_email(email: str) -> str:
    return email.strip().lower()


def assert_rate_limit(scope: str, key: str, max_events: int, window_seconds: int) -> None:
    """
    Zählt Events im Zeitfenster.
    Wenn Limit überschritten: blockieren.
    Sonst: neues Event speichern.
    """

    key = key.strip().lower()

    con = connect()
    cur = con.cursor()

    try:
        cur.execute(
            """
            DELETE FROM rate_limit_events
            WHERE created_at < now() - interval '24 hours'
            """
        )

        cur.execute(
            """
            SELECT COUNT(*) AS count
            FROM rate_limit_events
            WHERE scope = %s
              AND key = %s
              AND created_at > now() - (%s * interval '1 second')
            """,
            (scope, key, window_seconds),
        )

        row = cur.fetchone()
        count = row["count"]

        if count >= max_events:
            raise HTTPException(
                status_code=429,
                detail="Zu viele Versuche. Bitte später erneut versuchen."
            )

        cur.execute(
            """
            INSERT INTO rate_limit_events (scope, key)
            VALUES (%s, %s)
            """,
            (scope, key),
        )

        con.commit()

    finally:
        con.close()
