ALTER TABLE thoughts ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE thoughts ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
ALTER TABLE thoughts ADD COLUMN IF NOT EXISTS wallet_address TEXT;
ALTER TABLE thoughts ADD COLUMN IF NOT EXISTS eth_nonce BIGINT;
ALTER TABLE thoughts ADD COLUMN IF NOT EXISTS raw_transaction BYTEA;
ALTER TABLE thoughts ADD COLUMN IF NOT EXISTS last_error TEXT;
ALTER TABLE thoughts ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE thoughts ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;
ALTER TABLE thoughts ADD COLUMN IF NOT EXISTS claimed_by TEXT;
ALTER TABLE thoughts ADD COLUMN IF NOT EXISTS claim_until TIMESTAMPTZ;
ALTER TABLE thoughts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE thoughts DROP CONSTRAINT IF EXISTS thoughts_delivery_status_check;
ALTER TABLE thoughts ADD CONSTRAINT thoughts_delivery_status_check CHECK (
    status IS NULL OR status IN (
        'pending',
        'prepared',
        'needs_reconciliation',
        'broadcast',
        'mined',
        'failed'
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_thoughts_user_idempotency_key
ON thoughts(user_id, idempotency_key)
WHERE idempotency_key IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_thoughts_wallet_nonce
ON thoughts(wallet_address, eth_nonce)
WHERE wallet_address IS NOT NULL AND eth_nonce IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_thoughts_delivery_recovery
ON thoughts(status, next_retry_at, claim_until, created_at)
WHERE status IN ('pending', 'prepared', 'needs_reconciliation', 'broadcast');

CREATE TABLE IF NOT EXISTS ethereum_wallet_state (
    wallet_address TEXT PRIMARY KEY,
    next_nonce BIGINT NOT NULL,
    broadcast_claimed_by TEXT,
    broadcast_claim_until TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
