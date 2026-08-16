DO $$
DECLARE
    username_collisions TEXT;
    email_collisions TEXT;
BEGIN
    SELECT string_agg(
               format('%L (%s accounts)', normalized, account_count),
               ', '
               ORDER BY normalized
           )
    INTO username_collisions
    FROM (
        SELECT lower(username) AS normalized,
               count(*) AS account_count
        FROM users
        GROUP BY lower(username)
        HAVING count(*) > 1
    ) AS collisions;

    SELECT string_agg(
               format('%L (%s accounts)', normalized, account_count),
               ', '
               ORDER BY normalized
           )
    INTO email_collisions
    FROM (
        SELECT lower(email) AS normalized,
               count(*) AS account_count
        FROM users
        GROUP BY lower(email)
        HAVING count(*) > 1
    ) AS collisions;

    IF username_collisions IS NOT NULL OR email_collisions IS NOT NULL THEN
        RAISE EXCEPTION USING
            MESSAGE = format(
                'Case-insensitive user collisions block migration. Usernames: %s. Emails: %s.',
                coalesce(username_collisions, 'none'),
                coalesce(email_collisions, 'none')
            ),
            HINT = 'Resolve each collision explicitly; accounts were not modified.';
    END IF;
END $$;

CREATE UNIQUE INDEX uq_users_username_lower
ON users ((lower(username)));

CREATE UNIQUE INDEX uq_users_email_lower
ON users ((lower(email)));
