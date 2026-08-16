import asyncio
import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, patch

from dotenv import load_dotenv


ROOT = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(ROOT, ".env"))
os.environ.setdefault("ETH_PK", "0x" + "1" * 64)

from fastapi import HTTPException, Request

from app import rate_limit
from app import email_outbox
from app.db import connect, init_db
from app.migrations import run_migrations
from app.routers import auth
from app.schemas import SignupIn


class SignupQuotaTests(unittest.TestCase):
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
        self.prefix = f"q{uuid.uuid4().hex[:12]}"
        con = connect()
        try:
            with con.transaction():
                with con.cursor() as cur:
                    cur.execute("DELETE FROM signup_quota_allocations")
        finally:
            con.close()

    def tearDown(self):
        con = connect()
        try:
            with con.transaction():
                with con.cursor() as cur:
                    cur.execute(
                        "DELETE FROM users WHERE email LIKE %s",
                        (f"{self.prefix}%@example.com",),
                    )
        finally:
            con.close()

    def request(self, number=0):
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/signup",
                "headers": [],
                "client": (f"127.0.0.{number % 250 + 1}", 10000 + number),
            }
        )

    def payload(self, number=0, **changes):
        values = {
            "email": f"{self.prefix}{number}@example.com",
            "username": f"{self.prefix}_{number}",
            "password": "valid-password-123",
            "turnstile_token": "valid-turnstile-token",
        }
        values.update(changes)
        return SignupIn(**values)

    def call_signup(self, number=0, payload=None):
        return asyncio.run(
            auth.signup.__wrapped__(
                self.request(number),
                payload or self.payload(number),
            )
        )

    def quota_count(self):
        con = connect()
        try:
            with con.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS count FROM signup_quota_allocations")
                return cur.fetchone()["count"]
        finally:
            con.close()

    def user_count(self):
        con = connect()
        try:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS count FROM users WHERE email LIKE %s",
                    (f"{self.prefix}%@example.com",),
                )
                return cur.fetchone()["count"]
        finally:
            con.close()

    def signup_patches(self):
        return (
            patch.object(auth, "assert_rate_limit", return_value=None),
            patch.object(
                auth,
                "verify_turnstile_token",
                new=AsyncMock(return_value=None),
            ),
            patch.object(auth, "send_email", return_value=None),
        )

    def test_invalid_requests_do_not_consume_quota(self):
        patches = self.signup_patches()
        with patches[0], patches[1], patches[2]:
            with self.assertRaises(HTTPException) as honeypot:
                self.call_signup(1, self.payload(1, website="bot"))
            with self.assertRaises(HTTPException) as password:
                self.call_signup(2, self.payload(2, password="short"))

        self.assertEqual(honeypot.exception.status_code, 400)
        self.assertEqual(password.exception.status_code, 400)
        self.assertEqual(self.quota_count(), 0)
        self.assertEqual(self.user_count(), 0)

    def test_turnstile_failure_does_not_consume_quota(self):
        failure = HTTPException(status_code=403, detail="Turnstile failed")
        with (
            patch.object(auth, "assert_rate_limit", return_value=None),
            patch.object(
                auth,
                "verify_turnstile_token",
                new=AsyncMock(side_effect=failure),
            ),
            patch.object(auth, "send_email", return_value=None),
            self.assertRaises(HTTPException) as raised,
        ):
            self.call_signup()

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(self.quota_count(), 0)
        self.assertEqual(self.user_count(), 0)

    def test_duplicate_user_failure_does_not_consume_another_slot(self):
        patches = self.signup_patches()
        with patches[0], patches[1], patches[2]:
            self.call_signup(1)
            duplicate = self.payload(2, email=f"{self.prefix}1@example.com")
            with self.assertRaises(HTTPException) as raised:
                self.call_signup(2, duplicate)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.quota_count(), 1)
        self.assertEqual(self.user_count(), 1)

    def test_email_failure_is_retried_without_rolling_back_signup(self):
        with (
            patch.object(auth, "assert_rate_limit", return_value=None),
            patch.object(
                auth,
                "verify_turnstile_token",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                email_outbox,
                "send_email",
                side_effect=RuntimeError("email unavailable"),
            ),
        ):
            result = self.call_signup()
            self.assertFalse(email_outbox.deliver_once())

        self.assertTrue(result["ok"])
        self.assertEqual(self.quota_count(), 1)
        self.assertEqual(self.user_count(), 1)
        con = connect()
        try:
            with con.cursor() as cur:
                cur.execute(
                    """
                    SELECT status, attempt_count, last_error
                    FROM email_outbox
                    WHERE to_email = %s
                    """,
                    (self.payload().email,),
                )
                outbox = cur.fetchone()
        finally:
            con.close()
        self.assertEqual(outbox["status"], "retry")
        self.assertEqual(outbox["attempt_count"], 1)
        self.assertEqual(outbox["last_error"], "RuntimeError")

    def test_simultaneous_valid_requests_never_exceed_limit(self):
        request_count = 12
        limit = 4

        def submit(number):
            try:
                self.call_signup(number)
                return 200
            except HTTPException as exc:
                return exc.status_code

        patches = self.signup_patches()
        with (
            patches[0],
            patches[1],
            patches[2],
            patch.object(rate_limit, "MAX_SIGNUPS_PER_DAY", limit),
            ThreadPoolExecutor(max_workers=request_count) as executor,
        ):
            statuses = list(executor.map(submit, range(request_count)))

        self.assertEqual(statuses.count(200), limit)
        self.assertEqual(statuses.count(429), request_count - limit)
        self.assertEqual(self.quota_count(), limit)
        self.assertEqual(self.user_count(), limit)

    def test_separate_database_connections_share_one_quota(self):
        patches = self.signup_patches()
        with (
            patches[0],
            patches[1],
            patches[2],
            patch.object(rate_limit, "MAX_SIGNUPS_PER_DAY", 1),
        ):
            self.call_signup(1)
            with self.assertRaises(HTTPException) as raised:
                self.call_signup(2)

        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(self.quota_count(), 1)
        self.assertEqual(self.user_count(), 1)


if __name__ == "__main__":
    unittest.main()
