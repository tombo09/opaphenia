import os
import re
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from dotenv import load_dotenv


ROOT = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(ROOT, ".env"))

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.db import connect, init_db
from app.migrations import run_migrations
from app.routers import account, auth
from app.schemas import EmailUpdateIn
from app.security import create_access_token, hash_password, is_valid_token


class EmailChangeReauthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            init_db()
            run_migrations()
            con = connect()
            con.close()
        except Exception as exc:
            raise unittest.SkipTest(f"PostgreSQL is unavailable: {exc}")

        test_app = FastAPI()
        test_app.include_router(account.router, prefix="/api")
        cls.client = TestClient(test_app, raise_server_exceptions=False)

    def setUp(self):
        self.suffix = uuid.uuid4().hex
        self.old_email = f"old-{self.suffix}@example.com"
        self.password = "correct-password-123"
        con = connect()
        try:
            with con.transaction():
                with con.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO users
                            (email, username, password_hash, email_verified)
                        VALUES (%s, %s, %s, TRUE)
                        RETURNING id
                        """,
                        (
                            self.old_email,
                            f"email_change_{self.suffix}",
                            hash_password(self.password),
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
        finally:
            con.close()

    def request_change(self, email, password=None):
        sent = []
        with patch.object(
            account,
            "send_email",
            side_effect=lambda *args: sent.append(args),
        ):
            result = account.request_email_change(
                EmailUpdateIn(
                    email=email,
                    current_password=password or self.password,
                ),
                user_id=self.user_id,
            )
        token = re.search(r"token=([^\s]+)", sent[0][2]).group(1)
        return result, token

    def active_change_tokens(self):
        con = connect()
        try:
            with con.cursor() as cur:
                cur.execute(
                    """
                    SELECT token_hash, new_email
                    FROM email_verifications
                    WHERE user_id = %s
                      AND purpose = 'change_email'
                      AND used = FALSE
                    """,
                    (self.user_id,),
                )
                return cur.fetchall()
        finally:
            con.close()

    def current_email(self):
        con = connect()
        try:
            with con.cursor() as cur:
                cur.execute("SELECT email FROM users WHERE id = %s", (self.user_id,))
                return cur.fetchone()["email"]
        finally:
            con.close()

    def test_correct_password_creates_one_active_change_request(self):
        new_email = f"new-{self.suffix}@example.org"
        result, _ = self.request_change(new_email)
        self.assertTrue(result["ok"])
        active = self.active_change_tokens()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["new_email"], new_email)

    def test_wrong_password_rejected_without_token_changes(self):
        first_email = f"first-{self.suffix}@example.org"
        self.request_change(first_email)
        before = self.active_change_tokens()

        with (
            patch.object(account, "send_email") as send,
            self.assertRaises(HTTPException) as raised,
        ):
            account.request_email_change(
                EmailUpdateIn(
                    email=f"wrong-{self.suffix}@example.net",
                    current_password="wrong-password",
                ),
                user_id=self.user_id,
            )

        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(self.active_change_tokens(), before)
        send.assert_not_called()

    def test_authenticated_session_without_password_cannot_request_change(self):
        token = create_access_token(self.user_id, 1)
        response = self.client.put(
            "/api/account/request-email-change",
            json={"email": f"stolen-{self.suffix}@example.org"},
            cookies={"access_token": token},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.active_change_tokens(), [])

    def test_new_request_invalidates_old_and_old_cannot_change_email(self):
        first_email = f"first-{self.suffix}@example.org"
        second_email = f"second-{self.suffix}@example.net"
        _, first_token = self.request_change(first_email)
        _, second_token = self.request_change(second_email)

        active = self.active_change_tokens()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["new_email"], second_email)

        old_result = auth.verify_email(first_token)
        self.assertIn("already been used", old_result)
        self.assertEqual(self.current_email(), self.old_email)

        with patch.object(auth, "send_email"):
            auth.verify_email(second_token)
        self.assertEqual(self.current_email(), second_email)

    def test_concurrent_verification_has_one_transition_and_one_notification(self):
        new_email = f"concurrent-{self.suffix}@example.org"
        _, token = self.request_change(new_email)
        notifications = []
        notification_lock = threading.Lock()

        def record_notification(*args):
            with notification_lock:
                notifications.append(args)

        with patch.object(auth, "send_email", side_effect=record_notification):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: auth.verify_email(token), range(2)))

        self.assertEqual(
            sum("successfully verified" in result for result in results),
            1,
        )
        self.assertEqual(
            sum("already been used" in result for result in results),
            1,
        )
        self.assertEqual(self.current_email(), new_email)
        self.assertEqual(len(notifications), 1)

    def test_old_address_receives_token_free_security_notification(self):
        new_email = f"notice-{self.suffix}@example.org"
        _, token = self.request_change(new_email)
        sent = []
        with patch.object(
            auth,
            "send_email",
            side_effect=lambda *args: sent.append(args),
        ):
            auth.verify_email(token)

        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], self.old_email)
        self.assertNotIn(token, sent[0][1])
        self.assertNotIn(token, sent[0][2])

    def test_successful_email_change_revokes_existing_sessions(self):
        session = create_access_token(self.user_id, 1)
        new_email = f"revoke-{self.suffix}@example.org"
        _, verification_token = self.request_change(new_email)
        with patch.object(auth, "send_email"):
            auth.verify_email(verification_token)
        self.assertFalse(is_valid_token(session))


if __name__ == "__main__":
    unittest.main()
