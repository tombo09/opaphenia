import os
import unittest
import uuid
from unittest.mock import patch

from dotenv import load_dotenv


ROOT = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(ROOT, ".env"))

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app import utils
from app.db import connect
from app.main import create_app
from app.migrations import run_migrations
from app.routers import public, thoughts
from app.security import get_current_user_id


SENSITIVE_FIELDS = {
    "raw_transaction",
    "claimed_by",
    "claim_until",
    "eth_nonce",
    "receipt",
    "last_error",
}


class ThoughtDeliveryUxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            run_migrations()
            con = connect()
            con.close()
        except Exception as exc:
            raise unittest.SkipTest(f"PostgreSQL is unavailable: {exc}")

    def setUp(self):
        suffix = uuid.uuid4().hex
        con = connect()
        try:
            with con:
                with con.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO users
                            (email, username, password_hash, email_verified,
                             strings_public)
                        VALUES (%s, %s, 'unused', TRUE, TRUE)
                        RETURNING id, username
                        """,
                        (f"{suffix}@example.test", f"ux_{suffix}"),
                    )
                    owner = cur.fetchone()
                    self.user_id = owner["id"]
                    self.username = owner["username"]

                    cur.execute(
                        """
                        INSERT INTO users
                            (email, username, password_hash, email_verified)
                        VALUES (%s, %s, 'unused', TRUE)
                        RETURNING id
                        """,
                        (f"other_{suffix}@example.test", f"other_{suffix}"),
                    )
                    self.other_user_id = cur.fetchone()["id"]
        finally:
            con.close()

        api = FastAPI()
        api.include_router(thoughts.router, prefix="/api")
        api.include_router(public.router, prefix="/api")
        api.dependency_overrides[get_current_user_id] = lambda: self.user_id
        self.client = TestClient(api, raise_server_exceptions=False)

    def tearDown(self):
        self.client.close()
        con = connect()
        try:
            with con:
                with con.cursor() as cur:
                    cur.execute(
                        "DELETE FROM users WHERE id IN (%s, %s)",
                        (self.user_id, self.other_user_id),
                    )
        finally:
            con.close()

    def insert_thought(
        self,
        status,
        *,
        user_id=None,
        confirmation_count=None,
        confirmation_required=None,
        published=False,
        key=None,
    ):
        con = connect()
        try:
            with con:
                with con.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO thoughts
                            (user_id, content, hashed_string, status,
                             idempotency_key, txid, confirmation_count,
                             confirmation_required, published_at)
                        VALUES (%s, 'v1\n@owner\n\ncontent', '0x01', %s,
                                %s, %s, %s, %s,
                                CASE WHEN %s THEN now() ELSE NULL END)
                        RETURNING id
                        """,
                        (
                            user_id or self.user_id,
                            status,
                            key or uuid.uuid4().hex,
                            "0x" + "ab" * 32 if status != "pending" else None,
                            confirmation_count,
                            confirmation_required,
                            published,
                        ),
                    )
                    return cur.fetchone()["id"]
        finally:
            con.close()

    def assert_sanitized(self, payload):
        self.assertTrue(SENSITIVE_FIELDS.isdisjoint(payload))

    def test_post_returns_202_pending_projection_without_delivery_or_rpc(self):
        with (
            patch.object(thoughts, "moderate_text", return_value={"flagged": False}),
            patch.object(thoughts, "process_thought") as delivery,
            patch.object(utils, "rpc_call") as rpc,
        ):
            response = self.client.post(
                "/api/thoughts",
                headers={"Idempotency-Key": uuid.uuid4().hex},
                json={"content": "prompt return"},
            )

        self.assertEqual(response.status_code, 202, response.text)
        payload = response.json()
        self.assertEqual(payload["status"], "pending")
        self.assertEqual(payload["confirmation_count"], 0)
        self.assertEqual(payload["required_confirmations"], 12)
        self.assertFalse(payload["public_ready"])
        self.assertEqual(payload["public_url"], f"/{self.username}/{payload['id']}")
        self.assert_sanitized(payload)
        delivery.assert_not_called()
        rpc.assert_not_called()

    def test_owner_list_and_detail_expose_sanitized_confirmation_progress(self):
        thought_id = self.insert_thought(
            "confirming", confirmation_count=4, confirmation_required=12
        )
        with patch.object(utils, "rpc_call") as rpc:
            listed = self.client.get("/api/thoughts").json()["items"]
            detail = self.client.get(f"/api/thoughts/{thought_id}").json()

        item = next(row for row in listed if row["id"] == thought_id)
        for payload in (item, detail):
            self.assertEqual(payload["status"], "confirming")
            self.assertEqual(payload["confirmation_count"], 4)
            self.assertEqual(payload["required_confirmations"], 12)
            self.assertFalse(payload["public_ready"])
            self.assertEqual(payload["public_url"], f"/{self.username}/{thought_id}")
            self.assert_sanitized(payload)
        rpc.assert_not_called()

    def test_owner_list_keeps_every_delivery_state_visible(self):
        statuses = (
            "pending",
            "prepared",
            "needs_reconciliation",
            "broadcast",
            "confirming",
            "mined",
            "reverted",
            "failed",
        )
        expected = {self.insert_thought(status): status for status in statuses}

        items = {
            row["id"]: row["status"]
            for row in self.client.get("/api/thoughts").json()["items"]
        }
        for thought_id, status in expected.items():
            self.assertEqual(items[thought_id], status)

    def test_every_owner_projection_has_the_same_canonical_public_link(self):
        mined_id = self.insert_thought(
            "mined", confirmation_count=12, confirmation_required=12,
            published=True,
        )
        confirming_id = self.insert_thought(
            "confirming", confirmation_count=1, confirmation_required=12,
            published=True,
        )
        reverted_id = self.insert_thought("reverted")
        failed_id = self.insert_thought("failed")

        items = {row["id"]: row for row in self.client.get("/api/thoughts").json()["items"]}
        self.assertTrue(items[mined_id]["public_ready"])
        self.assertEqual(items[mined_id]["public_url"], f"/{self.username}/{mined_id}")
        self.assertTrue(items[confirming_id]["public_ready"])
        self.assertEqual(
            items[confirming_id]["public_url"],
            f"/{self.username}/{confirming_id}",
        )
        for thought_id in (reverted_id, failed_id):
            self.assertFalse(items[thought_id]["public_ready"])
            self.assertEqual(
                items[thought_id]["public_url"],
                f"/{self.username}/{thought_id}",
            )

    def test_owner_api_cannot_read_another_users_unfinished_thought(self):
        thought_id = self.insert_thought("confirming", user_id=self.other_user_id)
        response = self.client.get(f"/api/thoughts/{thought_id}")
        self.assertEqual(response.status_code, 404)

    def test_owner_shell_works_before_finality_but_canonical_route_does_not(self):
        pending_id = self.insert_thought("pending")
        confirming_id = self.insert_thought("confirming", published=True)
        mined_id = self.insert_thought("mined", published=True)
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)
        try:
            owner_page = client.get(f"/own/thoughts/{pending_id}")
            pending_public = client.get(f"/{self.username}/{pending_id}")
            confirming_public = client.get(f"/{self.username}/{confirming_id}")
            mined_public = client.get(f"/{self.username}/{mined_id}")
        finally:
            client.close()

        self.assertEqual(owner_page.status_code, 200)
        self.assertEqual(pending_public.status_code, 404)
        self.assertEqual(confirming_public.status_code, 200)
        self.assertEqual(mined_public.status_code, 200)

    def test_public_apis_use_publication_marker_not_delivery_state(self):
        ids = {
            status: self.insert_thought(status)
            for status in (
                "pending",
                "prepared",
                "broadcast",
                "confirming",
                "reverted",
                "failed",
            )
        }
        null_id = self.insert_thought(None)
        unpublished_mined_id = self.insert_thought("mined")
        published_confirming_id = self.insert_thought("confirming", published=True)
        mined_id = self.insert_thought("mined", published=True)

        public_ids = {
            row["id"]
            for row in public.public_thoughts_by_user(self.user_id)["items"]
        }
        self.assertEqual(public_ids, {published_confirming_id, mined_id})
        for thought_id in [*ids.values(), null_id, unpublished_mined_id]:
            with self.assertRaises(HTTPException) as raised:
                public.get_public_thought(thought_id)
            self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
