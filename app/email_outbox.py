import logging
import threading
import uuid

from app.db import connect
from app.email_utils import send_email


logger = logging.getLogger(__name__)

CLAIM_SECONDS = 60
WORKER_INTERVAL_SECONDS = 2
MAX_ATTEMPTS = 10


def enqueue_email(cur, *, user_id, kind, to_email, subject, body) -> int:
    cur.execute(
        """
        INSERT INTO email_outbox
            (user_id, kind, to_email, subject, body)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (user_id, kind, to_email, subject, body),
    )
    return cur.fetchone()["id"]


def _claim_one():
    claim_id = uuid.uuid4().hex
    con = connect()
    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    """
                    WITH candidate AS (
                        SELECT id
                        FROM email_outbox
                        WHERE (
                                status IN ('pending', 'retry')
                                AND next_attempt_at <= now()
                              )
                           OR (
                                status = 'sending'
                                AND claim_until < now()
                              )
                        ORDER BY next_attempt_at, created_at
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE email_outbox AS outbox
                    SET status = 'sending', claimed_by = %s,
                        claim_until = now() + (%s * interval '1 second'),
                        updated_at = now()
                    FROM candidate
                    WHERE outbox.id = candidate.id
                    RETURNING outbox.id, outbox.to_email, outbox.subject,
                              outbox.body, outbox.attempt_count,
                              outbox.claimed_by
                    """,
                    (claim_id, CLAIM_SECONDS),
                )
                return cur.fetchone()
    finally:
        con.close()


def _mark_sent(item) -> bool:
    con = connect()
    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    """
                    UPDATE email_outbox
                    SET status = 'sent', body = NULL, sent_at = now(),
                        attempt_count = attempt_count + 1,
                        claimed_by = NULL, claim_until = NULL,
                        next_attempt_at = now(), last_error = NULL,
                        updated_at = now()
                    WHERE id = %s AND status = 'sending' AND claimed_by = %s
                    """,
                    (item["id"], item["claimed_by"]),
                )
                return cur.rowcount == 1
    finally:
        con.close()


def _mark_failed(item, exc: Exception) -> bool:
    error = type(exc).__name__
    next_attempt = item["attempt_count"] + 1
    terminal = next_attempt >= MAX_ATTEMPTS
    delay = min(3600, 2 ** min(next_attempt, 11))
    con = connect()
    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    """
                    UPDATE email_outbox
                    SET status = %s, attempt_count = attempt_count + 1,
                        body = CASE WHEN %s THEN NULL ELSE body END,
                        next_attempt_at = now() + (%s * interval '1 second'),
                        last_error = %s, claimed_by = NULL,
                        claim_until = NULL, updated_at = now()
                    WHERE id = %s AND status = 'sending' AND claimed_by = %s
                    """,
                    (
                        "failed" if terminal else "retry",
                        terminal,
                        delay,
                        error,
                        item["id"],
                        item["claimed_by"],
                    ),
                )
                return cur.rowcount == 1
    finally:
        con.close()


def deliver_once() -> bool:
    item = _claim_one()
    if not item:
        return False

    try:
        send_email(item["to_email"], item["subject"], item["body"])
    except Exception as exc:
        _mark_failed(item, exc)
        logger.warning(
            "Email outbox delivery failed: outbox_id=%s attempt=%s error=%s",
            item["id"],
            item["attempt_count"] + 1,
            type(exc).__name__,
        )
        return False
    return _mark_sent(item)


def start_email_outbox_worker():
    stop_event = threading.Event()

    def run():
        while not stop_event.is_set():
            try:
                delivered = deliver_once()
            except Exception:
                logger.error("Email outbox worker iteration failed")
                delivered = False
            if not delivered:
                stop_event.wait(WORKER_INTERVAL_SECONDS)

    thread = threading.Thread(
        target=run,
        name="email-outbox",
        daemon=True,
    )
    thread.start()
    return stop_event, thread
