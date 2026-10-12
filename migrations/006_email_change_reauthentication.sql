WITH duplicate_active AS (
    SELECT id,
           row_number() OVER (
               PARTITION BY user_id
               ORDER BY created_at DESC, id DESC
           ) AS position
    FROM email_verifications
    WHERE purpose = 'change_email'
      AND used = FALSE
)
UPDATE email_verifications
SET used = TRUE
FROM duplicate_active
WHERE email_verifications.id = duplicate_active.id
  AND duplicate_active.position > 1;

CREATE UNIQUE INDEX uq_email_verifications_one_active_change_per_user
ON email_verifications(user_id)
WHERE purpose = 'change_email' AND used = FALSE;
