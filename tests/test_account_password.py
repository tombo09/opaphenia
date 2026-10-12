import os
import unittest
import uuid
from unittest.mock import patch

from dotenv import load_dotenv


ROOT = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(ROOT, ".env"))
os.environ.setdefault("ETH_PK", "0x" + "1" * 64)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import security
from app.config import COOKIE_NAME
from app.db import connect, init_db
from app.migrations import run_migrations
from app.routers import account


class AccountPasswordEndpointTests(unittest.TestCase):
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
        app.include_router(account.router, prefix="/api")
        cls.client = TestClient(app, raise_server_exceptions=False)

    def setUp(self):
        suffix = uuid.uuid4().hex
        self.old_password = "old-password-123"
        self.new_password = "new-password-456"
        old_hash = security.hash_password(self.old_password)
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
                            f"{suffix}@example.test",
                            f"password_{suffix}",
                            old_hash,
                        ),
                    )
                    row = cur.fetchone()
                    self.assertIsInstance(row, dict)
                    self.user_id = row["id"]
        finally:
            con.close()

        self.client.cookies.clear()
        self.client.cookies.set(
            COOKIE_NAME,
            security.create_access_token(self.user_id, 1),
        )

    def tearDown(self):
        self.client.cookies.clear()
        con = connect()
        try:
            with con.transaction():
                with con.cursor() as cur:
                    cur.execute("DELETE FROM users WHERE id = %s", (self.user_id,))
        finally:
            con.close()

    def password_hash(self):
        con = connect()
        try:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT password_hash FROM users WHERE id = %s",
                    (self.user_id,),
                )
                return cur.fetchone()["password_hash"]
        finally:
            con.close()

    def change_password(self, old_password=None, new_password=None):
        new_password = new_password or self.new_password
        return self.client.put(
            "/api/account/password",
            json={
                "old_password": old_password or self.old_password,
                "new_password": new_password,
                "new_password2": new_password,
            },
        )

    def test_correct_current_password_changes_hash_and_login_password(self):
        original_hash = self.password_hash()
        response = self.change_password()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"ok": True})
        changed_hash = self.password_hash()
        self.assertNotEqual(changed_hash, original_hash)
        self.assertTrue(security.verify_password(self.new_password, changed_hash))
        self.assertFalse(security.verify_password(self.old_password, changed_hash))

    def test_wrong_current_password_is_rejected_without_modification(self):
        original_hash = self.password_hash()
        response = self.change_password(old_password="incorrect-password")

        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(
            response.json()["detail"],
            "The old password is incorrect",
        )
        stored_hash = self.password_hash()
        self.assertEqual(stored_hash, original_hash)
        self.assertTrue(security.verify_password(self.old_password, stored_hash))

    def test_new_password_validation_does_not_modify_hash(self):
        original_hash = self.password_hash()
        response = self.client.put(
            "/api/account/password",
            json={
                "old_password": self.old_password,
                "new_password": "short",
                "new_password2": "different",
            },
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.password_hash(), original_hash)

    def test_database_failure_is_not_reported_as_bad_password(self):
        with patch.object(
            account,
            "connect",
            side_effect=RuntimeError("database unavailable"),
        ):
            response = self.change_password()

        self.assertEqual(response.status_code, 500, response.text)
        self.assertNotIn("old password", response.text.lower())
        self.assertTrue(
            security.verify_password(self.old_password, self.password_hash())
        )

    def test_unauthenticated_request_is_rejected(self):
        self.client.cookies.clear()
        response = self.change_password()

        self.assertEqual(response.status_code, 401, response.text)
        self.assertTrue(
            security.verify_password(self.old_password, self.password_hash())
        )


if __name__ == "__main__":
    unittest.main()
