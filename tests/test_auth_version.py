import os
import unittest
import uuid

from dotenv import load_dotenv


ROOT = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(ROOT, ".env"))

from fastapi import HTTPException
from jose import jwt
from starlette.requests import Request

from app import security
from app.config import ALGORITHM, COOKIE_NAME, SECRET_KEY
from app.db import connect, init_db
from app.migrations import run_migrations
from app.routers import account, auth
from app.schemas import PasswordUpdate
from app.utils import sha256


class AuthVersionTests(unittest.TestCase):
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
        suffix = uuid.uuid4().hex
        self.password = "original-password-123"
        con = connect()
        try:
            with con.transaction():
                with con.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO users
                            (email, username, password_hash, email_verified)
                        VALUES (%s, %s, %s, TRUE)
                        RETURNING id, auth_version
                        """,
                        (
                            f"auth-version-{suffix}@example.com",
                            f"auth_version_{suffix}",
                            security.hash_password(self.password),
                        ),
                    )
                    row = cur.fetchone()
                    self.user_id = row["id"]
                    self.assertEqual(row["auth_version"], 1)
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

    def auth_version(self):
        con = connect()
        try:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT auth_version FROM users WHERE id = %s",
                    (self.user_id,),
                )
                return cur.fetchone()["auth_version"]
        finally:
            con.close()

    def token(self, version=None):
        return security.create_access_token(
            self.user_id,
            self.auth_version() if version is None else version,
        )

    def request_for(self, token):
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/me",
                "headers": [
                    (b"cookie", f"{COOKIE_NAME}={token}".encode("ascii")),
                ],
            }
        )

    def assert_rejected(self, token):
        self.assertFalse(security.is_valid_token(token))
        with self.assertRaises(HTTPException) as raised:
            security.get_current_user_id(self.request_for(token))
        self.assertEqual(raised.exception.status_code, 401)

    def change_password(self):
        account.update_password(
            PasswordUpdate(
                old_password=self.password,
                new_password="replacement-password-123",
                new_password2="replacement-password-123",
            ),
            user_id=self.user_id,
        )

    def insert_reset(self, token):
        con = connect()
        try:
            with con.transaction():
                with con.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO password_resets
                            (user_id, token_hash, expires_at)
                        VALUES (%s, %s, now() + interval '30 minutes')
                        """,
                        (self.user_id, sha256(token)),
                    )
        finally:
            con.close()

    def test_old_jwt_is_revoked_immediately_after_password_change(self):
        old_token = self.token()
        self.change_password()
        self.assertEqual(self.auth_version(), 2)
        self.assert_rejected(old_token)

    def test_old_jwt_is_revoked_immediately_after_password_reset(self):
        old_token = self.token()
        reset_token = uuid.uuid4().hex
        self.insert_reset(reset_token)
        auth.password_reset_confirm(
            reset_token,
            "reset-password-123",
            "reset-password-123",
        )
        self.assertEqual(self.auth_version(), 2)
        self.assert_rejected(old_token)

    def test_newly_issued_jwt_works(self):
        self.change_password()
        new_token = self.token()
        self.assertTrue(security.is_valid_token(new_token))
        self.assertEqual(
            security.get_current_user_id(self.request_for(new_token)),
            self.user_id,
        )

    def test_wrong_password_does_not_revoke_sessions(self):
        existing_token = self.token()
        with self.assertRaises(HTTPException):
            account.update_password(
                PasswordUpdate(
                    old_password="wrong-password",
                    new_password="replacement-password-123",
                    new_password2="replacement-password-123",
                ),
                user_id=self.user_id,
            )
        self.assertEqual(self.auth_version(), 1)
        self.assertTrue(security.is_valid_token(existing_token))

    def test_failed_reset_does_not_revoke_sessions(self):
        existing_token = self.token()
        result = auth.password_reset_confirm(
            "invalid-reset-token",
            "reset-password-123",
            "reset-password-123",
        )
        self.assertIn("Invalid token", result)
        self.assertEqual(self.auth_version(), 1)
        self.assertTrue(security.is_valid_token(existing_token))

    def test_one_increment_revokes_two_previously_issued_jwts(self):
        first = self.token()
        second = self.token()
        self.change_password()
        self.assert_rejected(first)
        self.assert_rejected(second)

    def test_forged_stale_and_legacy_versions_are_rejected(self):
        self.assert_rejected(self.token(version=999))
        self.assert_rejected(self.token(version=0))
        legacy = jwt.encode(
            {"sub": str(self.user_id)},
            SECRET_KEY,
            algorithm=ALGORITHM,
        )
        self.assert_rejected(legacy)

    def test_migration_defaults_existing_and_new_users_to_version_one(self):
        con = connect()
        try:
            with con.transaction():
                with con.cursor() as cur:
                    cur.execute(
                        "DELETE FROM schema_migrations WHERE version = %s",
                        ("007_auth_version.sql",),
                    )
                    cur.execute("ALTER TABLE users DROP COLUMN auth_version")
        finally:
            con.close()

        run_migrations()

        con = connect()
        try:
            with con.cursor() as cur:
                cur.execute(
                    """
                    SELECT is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'users'
                      AND column_name = 'auth_version'
                    """
                )
                column = cur.fetchone()
        finally:
            con.close()
        self.assertEqual(column["is_nullable"], "NO")
        self.assertIn("1", column["column_default"])
        self.assertEqual(self.auth_version(), 1)


if __name__ == "__main__":
    unittest.main()
