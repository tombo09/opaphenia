ALTER TABLE thoughts DROP CONSTRAINT IF EXISTS thoughts_delivery_status_check;
ALTER TABLE thoughts ADD CONSTRAINT thoughts_delivery_status_check CHECK (
    status IS NULL OR status IN (
        'pending',
        'prepared',
        'needs_reconciliation',
        'broadcast',
        'mined',
        'reverted',
        'failed'
    )
);
