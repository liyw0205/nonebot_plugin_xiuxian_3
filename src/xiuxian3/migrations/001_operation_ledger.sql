CREATE TABLE operation_ledger (
    operation_id TEXT PRIMARY KEY,
    request_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('accepted', 'applied', 'rejected', 'failed', 'expired')),
    started_at TEXT NOT NULL,
    ended_at TEXT,
    result_digest TEXT,
    error_code TEXT
);

CREATE INDEX operation_ledger_actor_idx
    ON operation_ledger(actor_id, started_at);