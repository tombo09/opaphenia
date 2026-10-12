CREATE INDEX IF NOT EXISTS idx_rate_limit_events_created_at
ON rate_limit_events(created_at);
