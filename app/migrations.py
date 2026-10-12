from pathlib import Path

from app.db import connect


MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def run_migrations() -> None:
    con = connect()
    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version TEXT PRIMARY KEY,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )

        for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
            with con.transaction():
                with con.cursor() as cur:
                    cur.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        ("opaphenia-schema-migrations",),
                    )
                    cur.execute(
                        "SELECT 1 FROM schema_migrations WHERE version = %s",
                        (migration.name,),
                    )
                    if cur.fetchone():
                        continue
                    cur.execute(migration.read_text(encoding="utf-8"))
                    cur.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)",
                        (migration.name,),
                    )
    finally:
        con.close()
