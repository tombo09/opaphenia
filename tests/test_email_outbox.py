import asyncio
import os
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock, patch

from dotenv import load_dotenv


ROOT = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(ROOT, ".env"))

from fastapi import Request

from app import email_outbox
from app.db import connect, init_db
from app.migrations import run_migrations
from app.routers import auth
from app.schemas import SignupIn
from app.utils import sha256


class EmailOutboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            init_db()
            run_migrations()
            con = connect()
            con.close()
        except Exception as exc:
            raise unittest.SkipTest(f"PostgreSQL is unavailable: {exc}")

    def setUp(self):
        self.prefix = f"outbox-{uuid.uuid4().hex}"

    def tearDown(self):
        con = connect()
        try:
            with con.transaction():
                with con.cursor() as cur:
                    cur.execute(
                        "DELETE FROM users WHERE email LIKE %s",
                        (f"{self.prefix}%",),
                    )
        finally:
            con.close()

    def signup(self):
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/signup",
                "headers": [],
                "client": ("127.0.0.1", 12345),
            }
        )
        payload = SignupIn(
            email=f"{self.prefix}@example.com",
            username=self.prefix[:30],
            password="valid-password-123",
            turnstile_token="valid-token",
        )
        with (
            patch.object(auth, "assert_rate_limit", return_value=None),
            patch.object(
                auth,
                "verify_turnstile_token",
                new=AsyncMock(return_value=None),
            ),
        ):
            result = asyncio.run(auth.signup.__wrapped__(request, payload))
        return result, payload

    def outbox_row(self, email):
        con = connect()
        try:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT * FROM email_outbox WHERE to_email = %s",
                    (email,),
                )
                return cur.fetchone()
        finally:
            con.close()

    def make_due(self, outbox_id):
        con = connect()
        try:
            with con.transaction():
                with con.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE email_outbox
                        SET next_attempt_at = now() - interval '1 second'
                        WHERE id = %s
                        """,
                        (outbox_id,),
                    )
        finally:
            con.close()

    def test_signup_atomically_queues_email_without_calling_smtp(self):
        with patch.object(email_outbox, "send_email") as smtp:
            result, payload = self.signup()

        self.assertTrue(result["ok"])
        smtp.assert_not_called()
        outbox = self.outbox_row(payload.email)
        self.assertEqual(outbox["status"], "pending")
        self.assertEqual(outbox["attempt_count"], 0)

        con = connect()
        try:
            with con.cursor() as cur:
                cur.execute(
                    """
                    SELECT u.id, q.user_id, v.token_hash
                    FROM users u
                    JOIN signup_quota_allocations q ON q.user_id = u.id
                    JOIN email_verifications v ON v.user_id = u.id
                    WHERE u.email = %s
                    """,
                    (payload.email,),
                )
                durable = cur.fetchone()
        finally:
            con.close()
        self.assertIsNotNone(durable)

    def test_delivery_runs_after_quota_lock_is_released(self):
        _, payload = self.signup()

        def assert_lock_released(*_args):
            con = connect()
            try:
                with con.cursor() as cur:
                    cur.execute(
                        """
                        SELECT pg_try_advisory_lock(hashtextextended(
                            'global-signup-quota:' ||
                            ((now() AT TIME ZONE 'UTC')::date)::text,
                            0
                        )) AS acquired
                        """
                    )
                    acquired = cur.fetchone()["acquired"]
                    cur.execute(
                        """
                        SELECT pg_advisory_unlock(hashtextextended(
                            'global-signup-quota:' ||
                            ((now() AT TIME ZONE 'UTC')::date)::text,
                            0
                        ))
                        """
                    )
                    self.assertTrue(acquired)
            finally:
                con.close()

        with patch.object(email_outbox, "send_email", side_effect=assert_lock_released):
            self.assertTrue(email_outbox.deliver_once())
        self.assertEqual(self.outbox_row(payload.email)["status"], "sent")

    def test_crash_before_send_is_recovered_and_token_remains_valid(self):
        _, payload = self.signup()
        pending = self.outbox_row(payload.email)
        token = parse_qs(urlparse(pending["body"].split()[-1]).query)["token"][0]

        con = connect()
        try:
            with con.cursor() as cur:
                cur.execute(
                    """
                    SELECT used, expires_at > now() AS valid
                    FROM email_verifications
                    WHERE token_hash = %s
                    """,
                    (sha256(token),),
                )
                verification = cur.fetchone()
        finally:
            con.close()
        self.assertFalse(verification["used"])
        self.assertTrue(verification["valid"])

        with patch.object(email_outbox, "send_email") as smtp:
            self.assertTrue(email_outbox.deliver_once())
        smtp.assert_called_once()

    def test_failed_email_retries_and_sent_email_is_not_sent_twice(self):
        _, payload = self.signup()
        with patch.object(
            email_outbox,
            "send_email",
            side_effect=TimeoutError("sensitive SMTP response"),
        ):
            self.assertFalse(email_outbox.deliver_once())
        failed = self.outbox_row(payload.email)
        self.assertEqual(failed["status"], "retry")
        self.assertEqual(failed["last_error"], "TimeoutError")
        self.assertNotIn("sensitive", failed["last_error"])

        self.make_due(failed["id"])
        with patch.object(email_outbox, "send_email") as smtp:
            self.assertTrue(email_outbox.deliver_once())
            self.assertFalse(email_outbox.deliver_once())
        smtp.assert_called_once()
        sent = self.outbox_row(payload.email)
        self.assertEqual(sent["status"], "sent")
        self.assertIsNone(sent["body"])

    def test_two_workers_cannot_send_same_item_concurrently(self):
        _, payload = self.signup()
        entered = threading.Event()
        release = threading.Event()

        def slow_send(*_args):
            entered.set()
            release.wait(timeout=2)

        with (
            patch.object(email_outbox, "send_email", side_effect=slow_send) as smtp,
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            first = executor.submit(email_outbox.deliver_once)
            self.assertTrue(entered.wait(timeout=2))
            second = executor.submit(email_outbox.deliver_once)
            self.assertFalse(second.result(timeout=2))
            release.set()
            self.assertTrue(first.result(timeout=2))

        smtp.assert_called_once()
        self.assertEqual(self.outbox_row(payload.email)["status"], "sent")

    def test_stale_sending_claim_is_recoverable(self):
        _, payload = self.signup()
        pending = self.outbox_row(payload.email)
        con = connect()
        try:
            with con.transaction():
                with con.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE email_outbox
                        SET status = 'sending', claimed_by = 'crashed-worker',
                            claim_until = now() - interval '1 second'
                        WHERE id = %s
                        """,
                        (pending["id"],),
                    )
        finally:
            con.close()

        with patch.object(email_outbox, "send_email") as smtp:
            self.assertTrue(email_outbox.deliver_once())
        smtp.assert_called_once()
        self.assertEqual(self.outbox_row(payload.email)["status"], "sent")


if __name__ == "__main__":
    unittest.main()
