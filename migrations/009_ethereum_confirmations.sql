ALTER TABLE thoughts
ADD COLUMN IF NOT EXISTS confirmation_required INTEGER;

ALTER TABLE thoughts
ADD COLUMN IF NOT EXISTS confirmation_count INTEGER;

ALTER TABLE thoughts
ADD COLUMN IF NOT EXISTS confirmation_block_number BIGINT;

ALTER TABLE thoughts
ADD COLUMN IF NOT EXISTS confirmation_block_hash TEXT;

ALTER TABLE thoughts DROP CONSTRAINT IF EXISTS thoughts_delivery_status_check;
ALTER TABLE thoughts ADD CONSTRAINT thoughts_delivery_status_check CHECK (
    status IS NULL OR status IN (
        'pending',
        'prepared',
        'needs_reconciliation',
        'broadcast',
        'confirming',
        'mined',
        'reverted',
        'failed'
    )
);

DROP INDEX IF EXISTS idx_thoughts_delivery_recovery;
CREATE INDEX idx_thoughts_delivery_recovery
ON thoughts(status, next_retry_at, claim_until, created_at)
WHERE status IN (
    'pending',
    'prepared',
    'needs_reconciliation',
    'broadcast',
    'confirming'
);
