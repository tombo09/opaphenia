-- Thoughts created before the durable delivery state machine were inserted
-- only after the old synchronous Ethereum flow had completed. Preserve their
-- pre-upgrade visibility. Public access remains gated by users.strings_public.
UPDATE thoughts
SET published_at = COALESCE(blocktime, updated_at, created_at)
WHERE published_at IS NULL
  AND status IS NULL;
