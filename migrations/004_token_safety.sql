WITH duplicate_active AS (
    SELECT id,
           row_number() OVER (
               PARTITION BY user_id
               ORDER BY created_at DESC, id DESC
           ) AS position
    FROM password_resets
    WHERE used = FALSE
)
UPDATE password_resets
SET used = TRUE
FROM duplicate_active
WHERE password_resets.id = duplicate_active.id
  AND duplicate_active.position > 1;

CREATE UNIQUE INDEX IF NOT EXISTS uq_password_resets_one_active_per_user
ON password_resets(user_id)
WHERE used = FALSE;
