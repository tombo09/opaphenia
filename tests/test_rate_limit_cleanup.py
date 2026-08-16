import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv


ROOT = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(ROOT, ".env"))

from app import rate_limit
from app.db import connect, init_db
from app.migrations import run_migrations


class RateLimitCleanupTests(unittest.TestCase):
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
        self.scope = f"cleanup-{uuid.uuid4().hex}"
        con = connect()
        try:
            with con.transaction():
                with con.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM rate_limit_events
                        WHERE created_at < now() - interval '24 hours'
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
                        "DELETE FROM rate_limit_events WHERE scope = %s",
                        (self.scope,),
                    )
        finally:
            con.close()

    def insert_events(self, *, expired, active):
        con = connect()
        try:
            with con.transaction():
                with con.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO rate_limit_events (scope, key, created_at)
                        SELECT %s, 'key', now() - interval '25 hours'
                        FROM generate_series(1, %s)
                        """,
                        (self.scope, expired),
                    )
                    cur.execute(
                        """
                        INSERT INTO rate_limit_events (scope, key, created_at)
                        SELECT %s, 'key', now() - interval '1 minute'
                        FROM generate_series(1, %s)
                        """,
                        (self.scope, active),
                    )
        finally:
            con.close()

    def counts(self):
        con = connect()
        try:
            with con.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (
                            WHERE created_at < now() - interval '24 hours'
                        ) AS expired,
                        COUNT(*) FILTER (
                            WHERE created_at >= now() - interval '24 hours'
                        ) AS active
                    FROM rate_limit_events
                    WHERE scope = %s
                    """,
                    (self.scope,),
                )
                return cur.fetchone()
        finally:
            con.close()

    def test_expired_events_do_not_count_and_request_does_not_clean(self):
        self.insert_events(expired=3, active=0)
        rate_limit.assert_rate_limit(self.scope, "key", 1, 60 * 60)

        counts = self.counts()
        self.assertEqual(counts["expired"], 3)
        self.assertEqual(counts["active"], 1)

    def test_cleanup_removes_expired_and_preserves_active_rows(self):
        self.insert_events(expired=4, active=3)
        self.assertEqual(
            rate_limit.cleanup_expired_rate_limit_events(batch_size=10),
            4,
        )
        counts = self.counts()
        self.assertEqual(counts["expired"], 0)
        self.assertEqual(counts["active"], 3)

    def test_large_backlog_is_processed_in_bounded_batches(self):
        self.insert_events(expired=12, active=2)
        removed = rate_limit.cleanup_expired_rate_limit_events(batch_size=5)
        self.assertEqual(removed, 5)
        counts = self.counts()
        self.assertEqual(counts["expired"], 7)
        self.assertEqual(counts["active"], 2)

    def test_concurrent_cleanup_workers_are_safe(self):
        self.insert_events(expired=20, active=4)
        with ThreadPoolExecutor(max_workers=2) as executor:
            removed = list(
                executor.map(
                    rate_limit.cleanup_expired_rate_limit_events,
                    (10, 10),
                )
            )

        self.assertEqual(sum(removed), 20)
        counts = self.counts()
        self.assertEqual(counts["expired"], 0)
        self.assertEqual(counts["active"], 4)

    def test_cleanup_failure_does_not_affect_rate_limit_checks(self):
        self.insert_events(expired=1, active=0)
        original_connect = rate_limit.connect
        try:
            rate_limit.connect = lambda: (_ for _ in ()).throw(
                RuntimeError("cleanup unavailable")
            )
            with self.assertRaises(RuntimeError):
                rate_limit.cleanup_expired_rate_limit_events()
        finally:
            rate_limit.connect = original_connect

        rate_limit.assert_rate_limit(self.scope, "key", 1, 60 * 60)
        self.assertEqual(self.counts()["active"], 1)


if __name__ == "__main__":
    unittest.main()
