from fastapi import HTTPException

from app.db import connect
from datetime import date
from pathlib import Path
import json
import threading

from fastapi import HTTPException

MAX_SIGNUPS_PER_DAY = 10
SIGNUP_COUNTER_FILE = Path("signup_counter.json")
_signup_lock = threading.Lock()

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



def assert_global_signup_limit():
    today = str(date.today())

    with _signup_lock:
        if SIGNUP_COUNTER_FILE.exists():
            try:
                with open(SIGNUP_COUNTER_FILE, "r") as f:
                    counter = json.load(f)
            except Exception:
                counter = {"date": today, "count": 0}
        else:
            counter = {"date": today, "count": 0}

        if counter.get("date") != today:
            counter = {"date": today, "count": 0}

        if counter.get("count", 0) >= MAX_SIGNUPS_PER_DAY:
            raise HTTPException(
                status_code=429,
                detail="Daily signup limit reached. Please try again tomorrow.",
            )

        counter["count"] = counter.get("count", 0) + 1

        with open(SIGNUP_COUNTER_FILE, "w") as f:
            json.dump(counter, f)
