import os
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from dotenv import load_dotenv


ROOT = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(ROOT, ".env"))
os.environ.setdefault("ETH_PK", "0x" + "1" * 64)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import security
from app.db import connect, init_db
from app.migrations import run_migrations
from app.routers import auth
from app.utils import sha256


class AuthenticationTokenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            init_db()
            run_migrations()
            con = connect()
            con.close()
        except Exception as exc:
            raise unittest.SkipTest(f"PostgreSQL is unavailable: {exc}")

        app = FastAPI()
        app.include_router(auth.router, prefix="/api")
        cls.client = TestClient(app, raise_server_exceptions=False)

    def setUp(self):
        suffix = uuid.uuid4().hex
        self.email = f"reset-{suffix}@example.com"
        self.original_password = "original-password-123"
        con = connect()
        try:
            with con.transaction():
                with con.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM rate_limit_events
                        WHERE scope IN (
                            'password_reset_email',
                            'password_reset_ip',
                            'verification_resend_identifier',
                            'verification_resend_ip'
                        )
                        """
                    )
                    cur.execute(
                        """
                        INSERT INTO users
                            (email, username, password_hash,
                             email_verified, failed_attempts)
                        VALUES (%s, %s, %s, FALSE, 5)
                        RETURNING id
                        """,
                        (
                            self.email,
                            f"reset_{suffix[:20]}",
                            security.hash_password(self.original_password),
                        ),
                    )
                    self.user_id = cur.fetchone()["id"]
        finally:
            con.close()

    def tearDown(self):
        con = connect()
        try:
            with con.transaction():
                with con.cursor() as cur:
                    cur.execute("DELETE FROM users WHERE id = %s", (self.user_id,))
                    cur.execute(
                        """
                        DELETE FROM rate_limit_events
                        WHERE scope IN (
                            'password_reset_email',
                            'password_reset_ip',
                            'verification_resend_identifier',
                            'verification_resend_ip'
                        )
                        """
                    )
        finally:
            con.close()

    def reset_request(self, email=None, headers=None):
        return self.client.post(
            "/api/password-reset/request",
            json={"email": email or self.email},
            headers=headers,
        )

    def resend_verification_request(self, login=None, headers=None):
        return self.client.post(
            "/api/verification/resend",
            json={"login": login or self.email},
            headers=headers,
        )

    def insert_reset_token(self, token, *, used=False, expired=False):
        expires = datetime.now(timezone.utc) + (
            timedelta(minutes=-1 if expired else 30)
        )
        con = connect()
        try:
            with con.transaction():
                with con.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO password_resets
                            (user_id, token_hash, expires_at, used)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (self.user_id, sha256(token), expires, used),
                    )
        finally:
            con.close()

    def insert_verification_token(self, token, *, used=False, expired=False):
        expires = datetime.now(timezone.utc) + (
            timedelta(minutes=-1 if expired else 30)
        )
        con = connect()
        try:
            with con.transaction():
                with con.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO email_verifications
                            (user_id, purpose, token_hash, expires_at, used)
                        VALUES (%s, 'signup', %s, %s, %s)
                        """,
                        (self.user_id, sha256(token), expires, used),
                    )
        finally:
            con.close()

    def test_reset_request_is_rate_limited_by_normalized_email(self):
        missing = f"missing-{uuid.uuid4().hex}@example.com"
        with patch.object(auth, "send_email", return_value=None):
            responses = [
                self.reset_request(missing.upper()) for _ in range(4)
            ]

        self.assertEqual([r.status_code for r in responses], [200, 200, 200, 429])

    def test_reset_request_is_rate_limited_by_client_ip(self):
        with patch.object(auth, "send_email", return_value=None):
            responses = [
                self.reset_request(f"missing-{number}-{uuid.uuid4().hex}@example.com")
                for number in range(11)
            ]

        self.assertEqual([r.status_code for r in responses[:10]], [200] * 10)
        self.assertEqual(responses[10].status_code, 429)

    def test_untrusted_forwarded_for_cannot_bypass_reset_ip_limit(self):
        with patch.object(auth, "send_email", return_value=None):
            responses = [
                self.reset_request(
                    f"missing-{number}-{uuid.uuid4().hex}@example.com",
                    headers={"X-Forwarded-For": f"198.51.100.{number + 1}"},
                )
                for number in range(11)
            ]

        self.assertEqual([r.status_code for r in responses[:10]], [200] * 10)
        self.assertEqual(responses[10].status_code, 429)

    def test_reset_request_response_does_not_reveal_user_existence(self):
        with patch.object(auth, "send_email", return_value=None):
            existing = self.reset_request()
            missing = self.reset_request(
                f"missing-{uuid.uuid4().hex}@example.com"
            )

        self.assertEqual(existing.status_code, missing.status_code)
        self.assertEqual(existing.json(), missing.json())
        self.assertEqual(existing.json(), {"ok": True})

        reset_token = "reset-token-must-not-be-logged"
        sensitive_error = (
            f"SMTP failure for {self.email}; password=secret; "
            f"token={reset_token}; smtp-password=credential"
        )
        with (
            patch.object(auth.secrets, "token_urlsafe", return_value=reset_token),
            patch.object(
                auth,
                "send_email",
                side_effect=RuntimeError(sensitive_error),
            ),
            self.assertLogs(auth.logger, level="WARNING") as captured,
        ):
            delivery_failure = self.reset_request()

        self.assertEqual(delivery_failure.status_code, missing.status_code)
        self.assertEqual(delivery_failure.json(), missing.json())
        log_output = "\n".join(captured.output)
        self.assertIn("operation=password_reset_request", log_output)
        self.assertIn("error=RuntimeError", log_output)
        for secret in (
            self.email,
            reset_token,
            "secret",
            "credential",
            sensitive_error,
        ):
            self.assertNotIn(secret, log_output)

        with (
            patch.object(auth, "connect", side_effect=RuntimeError("database down")),
            self.assertLogs(auth.logger, level="WARNING") as database_logs,
        ):
            database_failure = self.reset_request(
                f"database-{uuid.uuid4().hex}@example.com"
            )
        self.assertEqual(database_failure.status_code, missing.status_code)
        self.assertEqual(database_failure.json(), missing.json())
        self.assertIn("error=RuntimeError", "\n".join(database_logs.output))

        with (
            patch.object(
                auth,
                "assert_rate_limit",
                side_effect=RuntimeError("rate-limit database down"),
            ),
            self.assertLogs(auth.logger, level="WARNING") as rate_limit_logs,
        ):
            rate_limit_failure = self.reset_request(
                f"rate-limit-{uuid.uuid4().hex}@example.com"
            )
        self.assertEqual(rate_limit_failure.status_code, missing.status_code)
        self.assertEqual(rate_limit_failure.json(), missing.json())
        self.assertIn("stage=rate_limit", "\n".join(rate_limit_logs.output))

    def test_expired_signup_verification_can_be_reissued(self):
        old_token = uuid.uuid4().hex
        self.insert_verification_token(old_token, expired=True)
        con = connect()
        try:
            with con.transaction():
                with con.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO email_outbox
                            (user_id, kind, to_email, subject, body)
                        VALUES (%s, 'signup_verification', %s,
                                'Verify your email', %s)
                        """,
                        (
                            self.user_id,
                            self.email,
                            f"Click to verify: old?token={old_token}",
                        ),
                    )
        finally:
            con.close()

        response = self.resend_verification_request()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), auth.VERIFICATION_RESEND_RESPONSE)

        con = connect()
        try:
            with con.cursor() as cur:
                cur.execute(
                    """
                    SELECT token_hash, used, expires_at > now() AS valid
                    FROM email_verifications
                    WHERE user_id = %s AND purpose = 'signup'
                    ORDER BY created_at, id
                    """,
                    (self.user_id,),
                )
                tokens = cur.fetchall()
                cur.execute(
                    """
                    SELECT status, body
                    FROM email_outbox
                    WHERE user_id = %s AND kind = 'signup_verification'
                    ORDER BY created_at, id
                    """,
                    (self.user_id,),
                )
                emails = cur.fetchall()
                cur.execute(
                    "SELECT email_verified FROM users WHERE id = %s",
                    (self.user_id,),
                )
                account = cur.fetchone()
        finally:
            con.close()

        self.assertEqual(len(tokens), 2)
        self.assertTrue(tokens[0]["used"])
        self.assertFalse(tokens[1]["used"])
        self.assertTrue(tokens[1]["valid"])
        self.assertEqual(emails[0]["status"], "failed")
        self.assertIsNone(emails[0]["body"])
        self.assertEqual(emails[1]["status"], "pending")
        new_token = parse_qs(
            urlparse(emails[1]["body"].split()[-1]).query
        )["token"][0]
        self.assertEqual(tokens[1]["token_hash"], sha256(new_token))
        self.assertFalse(account["email_verified"])
        self.assertIn("successfully verified", auth.verify_email(new_token))

    def test_verification_resend_response_does_not_reveal_account_state(self):
        missing = self.resend_verification_request(
            f"missing-{uuid.uuid4().hex}"
        )
        con = connect()
        try:
            with con.transaction():
                with con.cursor() as cur:
                    cur.execute(
                        "UPDATE users SET email_verified = TRUE WHERE id = %s",
                        (self.user_id,),
                    )
        finally:
            con.close()
        verified = self.resend_verification_request()

        self.assertEqual(missing.status_code, 200)
        self.assertEqual(verified.status_code, 200)
        self.assertEqual(missing.json(), verified.json())
        self.assertEqual(verified.json(), auth.VERIFICATION_RESEND_RESPONSE)

        con = connect()
        try:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT count(*) AS count FROM email_outbox WHERE user_id = %s",
                    (self.user_id,),
                )
                queued = cur.fetchone()["count"]
        finally:
            con.close()
        self.assertEqual(queued, 0)

    def test_verification_resend_is_rate_limited_by_identifier(self):
        missing = f"missing-{uuid.uuid4().hex}"
        responses = [
            self.resend_verification_request(missing) for _ in range(4)
        ]
        self.assertEqual(
            [response.status_code for response in responses],
            [200, 200, 200, 429],
        )

    def test_concurrent_verification_resends_queue_only_one_email(self):
        old_token = uuid.uuid4().hex
        self.insert_verification_token(old_token, expired=True)
        barrier = threading.Barrier(2)

        def resend():
            barrier.wait()
            auth._queue_verification_resend(self.email)

        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(lambda _: resend(), range(2)))

        con = connect()
        try:
            with con.cursor() as cur:
                cur.execute(
                    """
                    SELECT count(*) FILTER (WHERE used = FALSE) AS active
                    FROM email_verifications
                    WHERE user_id = %s AND purpose = 'signup'
                    """,
                    (self.user_id,),
                )
                active = cur.fetchone()["active"]
                cur.execute(
                    """
                    SELECT count(*) AS count
                    FROM email_outbox
                    WHERE user_id = %s
                      AND kind = 'signup_verification'
                      AND status = 'pending'
                    """,
                    (self.user_id,),
                )
                queued = cur.fetchone()["count"]
        finally:
            con.close()

        self.assertEqual(active, 1)
        self.assertEqual(queued, 1)

    def test_new_reset_invalidates_old_and_only_one_is_active(self):
        links = []

        def capture_email(to_email, subject, body):
            links.append(body.split()[-1])

        with patch.object(auth, "send_email", side_effect=capture_email):
            self.assertEqual(self.reset_request().status_code, 200)
            self.assertEqual(self.reset_request().status_code, 200)

        old_token = parse_qs(urlparse(links[0]).query)["token"][0]
        new_token = parse_qs(urlparse(links[1]).query)["token"][0]
        con = connect()
        try:
            with con.cursor() as cur:
                cur.execute(
                    """
                    SELECT token_hash, used
                    FROM password_resets
                    WHERE user_id = %s
                    ORDER BY created_at, id
                    """,
                    (self.user_id,),
                )
                rows = cur.fetchall()
        finally:
            con.close()

        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(not row["used"] for row in rows), 1)
        states = {row["token_hash"]: row["used"] for row in rows}
        self.assertTrue(states[sha256(old_token)])
        self.assertFalse(states[sha256(new_token)])

    def test_concurrent_reset_token_consumption_has_one_winner(self):
        token = secrets_token = uuid.uuid4().hex
        self.insert_reset_token(token)
        barrier = threading.Barrier(2)

        def consume():
            barrier.wait()
            return auth.password_reset_confirm(
                token=secrets_token,
                new_password="replacement-password-123",
                new_password2="replacement-password-123",
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: consume(), range(2)))

        self.assertEqual(sum("has been changed" in result for result in results), 1)
        self.assertEqual(sum("already been used" in result for result in results), 1)

    def test_concurrent_verification_token_consumption_has_one_winner(self):
        token = uuid.uuid4().hex
        self.insert_verification_token(token)
        barrier = threading.Barrier(2)

        def consume():
            barrier.wait()
            return auth.verify_email(token)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: consume(), range(2)))

        self.assertEqual(sum("successfully verified" in result for result in results), 1)
        self.assertEqual(sum("already been used" in result for result in results), 1)

    def test_expired_tokens_are_rejected(self):
        reset_token = uuid.uuid4().hex
        verification_token = uuid.uuid4().hex
        self.insert_reset_token(reset_token, expired=True)
        self.insert_verification_token(verification_token, expired=True)

        reset_result = auth.password_reset_confirm(
            token=reset_token,
            new_password="replacement-password-123",
            new_password2="replacement-password-123",
        )
        verification_result = auth.verify_email(verification_token)

        self.assertIn("expired", reset_result)
        self.assertIn("expired", verification_result)

    def test_used_tokens_are_rejected(self):
        reset_token = uuid.uuid4().hex
        verification_token = uuid.uuid4().hex
        self.insert_reset_token(reset_token, used=True)
        self.insert_verification_token(verification_token, used=True)

        reset_result = auth.password_reset_confirm(
            token=reset_token,
            new_password="replacement-password-123",
            new_password2="replacement-password-123",
        )
        verification_result = auth.verify_email(verification_token)

        self.assertIn("already been used", reset_result)
        self.assertIn("already been used", verification_result)


if __name__ == "__main__":
    unittest.main()
