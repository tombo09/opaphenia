CREATE TABLE IF NOT EXISTS signup_quota_allocations (
    user_id BIGINT PRIMARY KEY,
    quota_date DATE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_signup_quota_allocations_date
ON signup_quota_allocations(quota_date);
