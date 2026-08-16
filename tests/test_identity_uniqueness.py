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

from fastapi import HTTPException, Request, Response

from app import security
from app.db import connect, init_db
from app.migrations import run_migrations
from app.routers import auth, public
from app.schemas import LoginIn, ResetRequestIn, SignupIn


class CaseInsensitiveIdentityTests(unittest.TestCase):
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
        self.prefix = f"ci{uuid.uuid4().hex[:10]}"
        con = connect()
        try:
            with con.transaction():
                with con.cursor() as cur:
                    cur.execute("DELETE FROM signup_quota_allocations")
                    cur.execute(
                        """
                        DELETE FROM rate_limit_events
                        WHERE scope LIKE 'signup_%'
                           OR scope LIKE 'password_reset_%'
                           OR scope = 'login_user'
                        """
                    )
        finally:
            con.close()

    def tearDown(self):
        con = connect()
        try:
            with con.transaction():
                with con.cursor() as cur:
                    cur.execute(
                        "DELETE FROM users WHERE lower(email) LIKE %s",
                        (f"{self.prefix}%@example.com",),
                    )
                    cur.execute("DELETE FROM signup_quota_allocations")
        finally:
            con.close()

    def request(self, number=0):
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/signup",
                "headers": [],
                "client": (f"127.1.0.{number + 1}", 12000 + number),
            }
        )

    def payload(self, username, email):
        return SignupIn(
            username=username,
            email=email,
            password="valid-password-123",
            turnstile_token="valid-token",
        )

    def signup(self, number, username, email):
        return asyncio.run(
            auth.signup.__wrapped__(
                self.request(number),
                self.payload(username, email),
            )
        )

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

    def user_count(self):
        con = connect()
        try:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS count FROM users WHERE lower(email) LIKE %s",
                    (f"{self.prefix}%@example.com",),
                )
                return cur.fetchone()["count"]
        finally:
            con.close()

    def test_username_differing_only_by_case_is_rejected(self):
        patches = self.signup_patches()
        with patches[0], patches[1], patches[2]:
            self.signup(1, "Alice", f"{self.prefix}1@example.com")
            with self.assertRaises(HTTPException) as raised:
                self.signup(2, "alice", f"{self.prefix}2@example.com")

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.user_count(), 1)

    def test_email_differing_only_by_case_is_rejected(self):
        email = f"{self.prefix}@example.com"
        patches = self.signup_patches()
        with patches[0], patches[1], patches[2]:
            self.signup(1, f"{self.prefix}One", email)
            with self.assertRaises(HTTPException) as raised:
                self.signup(2, f"{self.prefix}Two", email.upper())

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.user_count(), 1)

    def test_login_and_public_lookup_are_case_insensitive_and_unambiguous(self):
        email = f"{self.prefix}@example.com"
        username = f"{self.prefix}Alice"
        patches = self.signup_patches()
        with patches[0], patches[1], patches[2]:
            self.signup(1, username, email)

        con = connect()
        try:
            with con.transaction():
                with con.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE users
                        SET email_verified = TRUE, strings_public = TRUE
                        WHERE email = %s
                        RETURNING id
                        """,
                        (email,),
                    )
                    user_id = cur.fetchone()["id"]
        finally:
            con.close()

        with patch.object(auth, "assert_rate_limit", return_value=None):
            login_result = auth.login.__wrapped__(
                self.request(),
                LoginIn(login=username.swapcase(), password="valid-password-123"),
                Response(),
            )
        profile = public.public_user_by_username(username.swapcase())

        self.assertEqual(login_result, {"ok": True})
        self.assertEqual(profile["user"]["id"], user_id)
        self.assertEqual(profile["user"]["username"], username)

    def test_password_reset_resolves_mixed_case_stored_email(self):
        stored_email = f"{self.prefix}Mixed@Example.COM"
        con = connect()
        try:
            with con.transaction():
                with con.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO users
                            (email, username, password_hash,
                             email_verified, failed_attempts)
                        VALUES (%s, %s, %s, TRUE, 5)
                        """,
                        (
                            stored_email,
                            f"{self.prefix}Reset",
                            security.hash_password("valid-password-123"),
                        ),
                    )
        finally:
            con.close()

        sent_to = []
        with (
            patch.object(auth, "assert_rate_limit", return_value=None),
            patch.object(
                auth,
                "send_email",
                side_effect=lambda address, subject, body: sent_to.append(address),
            ),
        ):
            result = auth.password_reset_request(
                self.request(),
                ResetRequestIn(email=stored_email.swapcase()),
            )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(sent_to, [stored_email.lower()])

    def test_concurrent_case_colliding_signups_create_one_account(self):
        def submit(number):
            try:
                self.signup(
                    number,
                    "ConcurrentAlice" if number == 0 else "concurrentalice",
                    f"{self.prefix}{number}@example.com",
                )
                return 200
            except HTTPException as exc:
                return exc.status_code

        patches = self.signup_patches()
        with (
            patches[0],
            patches[1],
            patches[2],
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            statuses = list(executor.map(submit, range(2)))

        self.assertEqual(sorted(statuses), [200, 409])
        self.assertEqual(self.user_count(), 1)


if __name__ == "__main__":
    unittest.main()
