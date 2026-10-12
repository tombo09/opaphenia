import os
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from dotenv import load_dotenv


ROOT = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(ROOT, ".env"))
os.environ.setdefault("ETH_PK", "0x" + "1" * 64)

from fastapi import HTTPException

from app.db import connect
from app.migrations import run_migrations
from app.routers import thoughts
from app.schemas import ThoughtIn
from app import thought_delivery, utils
from tests.test_thought_delivery_recovery import FakeAccount, FakeChain


class ThoughtConcurrencyTests(unittest.TestCase):
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
                            (email, username, password_hash, email_verified)
                        VALUES (%s, %s, %s, TRUE)
                        RETURNING id
                        """,
                        (f"{suffix}@example.test", f"user_{suffix}", "unused"),
                    )
                    self.user_id = cur.fetchone()["id"]
        finally:
            con.close()

    def tearDown(self):
        con = connect()
        try:
            with con:
                with con.cursor() as cur:
                    cur.execute("DELETE FROM users WHERE id = %s", (self.user_id,))
        finally:
            con.close()

    def test_ten_simultaneous_requests_create_at_most_two_thoughts(self):
        barrier = threading.Barrier(10)
        def submit(number):
            barrier.wait()
            try:
                thoughts.create_thought(
                    ThoughtIn(content=f"thought-{number}"),
                    user_id=self.user_id,
                    idempotency_key=f"concurrency-{number}",
                )
                return 200
            except HTTPException as exc:
                return exc.status_code

        with (
            patch.object(thoughts, "moderate_text", return_value={"flagged": False}),
            patch.object(
                thoughts,
                "process_thought",
                side_effect=lambda thought_id, wait_for_receipt: {
                    "status": "mined"
                },
            ),
            ThreadPoolExecutor(max_workers=10) as executor,
        ):
            statuses = list(executor.map(submit, range(10)))

        con = connect()
        try:
            with con.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM thoughts
                    WHERE user_id = %s
                      AND created_at >= date_trunc('day', now())
                      AND created_at < date_trunc('day', now()) + interval '1 day'
                    """,
                    (self.user_id,),
                )
                count = cur.fetchone()["cnt"]
        finally:
            con.close()

        self.assertEqual(statuses.count(200), 2)
        self.assertEqual(statuses.count(429), 8)
        self.assertEqual(count, 2)

    def test_concurrent_wallet_sends_use_unique_nonces(self):
        wallet = "0x" + uuid.uuid4().hex[:40].ljust(40, "0")
        chain = FakeChain()
        con = connect()
        try:
            with con:
                with con.cursor() as cur:
                    thought_ids = []
                    for number in range(10):
                        cur.execute(
                            """
                            INSERT INTO thoughts
                                (user_id, content, hashed_string, status,
                                 idempotency_key, wallet_address)
                            VALUES (%s, %s, %s, 'pending', %s, %s)
                            RETURNING id
                            """,
                            (
                                self.user_id,
                                f"thought-{number}",
                                f"0x{number + 1:02x}",
                                f"wallet-concurrency-{number}",
                                wallet.lower(),
                            ),
                        )
                        thought_ids.append(cur.fetchone()["id"])
        finally:
            con.close()

        with (
            patch.object(
                utils,
                "get_ethereum_signer",
                return_value=utils.EthereumSigner(
                    account=FakeAccount(), address=wallet
                ),
            ),
            patch.object(utils, "rpc_call", side_effect=chain.rpc_call),
        ):
            for _ in range(20):
                con = connect()
                try:
                    with con:
                        with con.cursor() as cur:
                            cur.execute(
                                """
                                UPDATE thoughts
                                SET next_retry_at = NULL,
                                    claimed_by = NULL,
                                    claim_until = NULL
                                WHERE id = ANY(%s) AND status = 'pending'
                                """,
                                (thought_ids,),
                            )
                finally:
                    con.close()

                with ThreadPoolExecutor(max_workers=10) as executor:
                    list(executor.map(thought_delivery.process_thought, thought_ids))

                con = connect()
                try:
                    with con.cursor() as cur:
                        cur.execute(
                            """
                            SELECT COUNT(*) AS cnt
                            FROM thoughts
                            WHERE id = ANY(%s) AND status = 'broadcast'
                            """,
                            (thought_ids,),
                        )
                        if cur.fetchone()["cnt"] == 10:
                            break
                finally:
                    con.close()

        con = connect()
        try:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT eth_nonce FROM thoughts WHERE id = ANY(%s)",
                    (thought_ids,),
                )
                sent_nonces = [row["eth_nonce"] for row in cur.fetchall()]
        finally:
            con.close()

        self.assertEqual(len(sent_nonces), 10)
        self.assertEqual(len(set(sent_nonces)), 10)
        self.assertEqual(sorted(sent_nonces), list(range(10)))
        self.assertEqual(chain.send_calls, 10)

        con = connect()
        try:
            with con:
                with con.cursor() as cur:
                    cur.execute(
                        "DELETE FROM ethereum_wallet_state WHERE wallet_address = %s",
                        (wallet.lower(),),
                    )
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
