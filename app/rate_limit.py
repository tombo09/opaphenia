import logging
import threading

from app.db import connect

from fastapi import HTTPException

MAX_SIGNUPS_PER_DAY = 10
RATE_LIMIT_RETENTION_HOURS = 24
RATE_LIMIT_CLEANUP_BATCH_SIZE = 500
RATE_LIMIT_CLEANUP_INTERVAL_SECONDS = 300

logger = logging.getLogger(__name__)

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
    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    """
                    SELECT pg_advisory_xact_lock(
                        hashtextextended(%s, 0)
                    )
                    """,
                    (f"rate-limit:{scope}:{key}",),
                )
                cur.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM rate_limit_events
                    WHERE scope = %s
                      AND key = %s
                      AND created_at > now() - (
                          %s * interval '1 second'
                      )
                    """,
                    (scope, key, window_seconds),
                )
                if cur.fetchone()["count"] >= max_events:
                    raise HTTPException(
                        status_code=429,
                        detail=(
                            "Zu viele Versuche. "
                            "Bitte später erneut versuchen."
                        ),
                    )
                cur.execute(
                    """
                    INSERT INTO rate_limit_events (scope, key)
                    VALUES (%s, %s)
                    """,
                    (scope, key),
                )
    finally:
        con.close()


def cleanup_expired_rate_limit_events(
    batch_size: int = RATE_LIMIT_CLEANUP_BATCH_SIZE,
) -> int:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    con = connect()
    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    """
                    WITH expired AS (
                        SELECT id
                        FROM rate_limit_events
                        WHERE created_at < now() - (
                            %s * interval '1 hour'
                        )
                        ORDER BY created_at
                        FOR UPDATE SKIP LOCKED
                        LIMIT %s
                    )
                    DELETE FROM rate_limit_events AS events
                    USING expired
                    WHERE events.id = expired.id
                    """,
                    (RATE_LIMIT_RETENTION_HOURS, batch_size),
                )
                return cur.rowcount
    finally:
        con.close()


def start_rate_limit_cleanup_worker():
    stop_event = threading.Event()

    def run():
        while not stop_event.is_set():
            try:
                cleanup_expired_rate_limit_events()
            except Exception:
                logger.error("Rate-limit cleanup iteration failed")
            stop_event.wait(RATE_LIMIT_CLEANUP_INTERVAL_SECONDS)

    thread = threading.Thread(
        target=run,
        name="rate-limit-cleanup",
        daemon=True,
    )
    thread.start()
    return stop_event, thread



def assert_global_daily_signup_limit(cur):
    cur.execute(
        """
        SELECT pg_advisory_xact_lock(
            hashtextextended(
                'global-signup-quota:' ||
                ((now() AT TIME ZONE 'UTC')::date)::text,
                0
            )
        )
        """
    )
    cur.execute(
        """
        SELECT COUNT(*) AS count,
               (now() AT TIME ZONE 'UTC')::date AS quota_date
        FROM signup_quota_allocations
        WHERE quota_date = (now() AT TIME ZONE 'UTC')::date
        """
    )
    row = cur.fetchone()
    if row["count"] >= MAX_SIGNUPS_PER_DAY:
        raise HTTPException(
            status_code=429,
            detail="Daily signup limit reached. Please try again tomorrow.",
        )
    return row["quota_date"]
