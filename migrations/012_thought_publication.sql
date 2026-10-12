ALTER TABLE thoughts
ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;

-- Only delivery states produced after a validated successful receipt are
-- eligible for compatibility publication. Legacy NULL-state rows and rows
-- without matching successful receipt metadata remain private.
UPDATE thoughts
SET published_at = COALESCE(blocktime, updated_at, created_at)
WHERE published_at IS NULL
  AND status IN ('confirming', 'mined')
  AND txid IS NOT NULL
  AND lower(receipt ->> 'transactionHash') = lower(txid)
  AND lower(receipt ->> 'status') IN ('0x1', '0x01');

CREATE INDEX IF NOT EXISTS idx_thoughts_publication_by_user
ON thoughts(user_id, created_at DESC)
WHERE published_at IS NOT NULL;
