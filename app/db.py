import psycopg
from psycopg.rows import dict_row
from app.config import DATABASE_URL


def connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL fehlt (ENV).")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db():
    schema_sql = """
    CREATE TABLE IF NOT EXISTS users (
      id BIGSERIAL PRIMARY KEY,
      email TEXT NOT NULL UNIQUE,
      username TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL,
      email_verified BOOLEAN NOT NULL DEFAULT FALSE,
      strings_public BOOLEAN NOT NULL DEFAULT FALSE,
      failed_attempts INT NOT NULL DEFAULT 0,
      auth_version BIGINT NOT NULL DEFAULT 1,
      timezone TEXT NOT NULL DEFAULT 'Europe/Berlin'
    );

    CREATE TABLE IF NOT EXISTS email_verifications (
      id BIGSERIAL PRIMARY KEY,
      user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      purpose TEXT NOT NULL,
      new_email TEXT,
      token_hash TEXT NOT NULL UNIQUE,
      expires_at TIMESTAMPTZ NOT NULL,
      used BOOLEAN NOT NULL DEFAULT FALSE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS thoughts (
      id BIGSERIAL PRIMARY KEY,
      user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      content TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      blocktime TIMESTAMPTZ,
      hashed_string TEXT,
      txid TEXT
    );

    CREATE TABLE IF NOT EXISTS password_resets (
      id BIGSERIAL PRIMARY KEY,
      user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      token_hash TEXT NOT NULL UNIQUE,
      expires_at TIMESTAMPTZ NOT NULL,
      used BOOLEAN NOT NULL DEFAULT FALSE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE IF NOT EXISTS rate_limit_events (
        id BIGSERIAL PRIMARY KEY,
        scope TEXT NOT NULL,
        key TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_rate_limit_events_scope_key_created
    ON rate_limit_events(scope, key, created_at);
    """
    con = connect()
    with con:
        with con.cursor() as cur:
            cur.execute(schema_sql)
    con.close()
