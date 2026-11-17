"""Additive finite-resource projections bound to immutable operation receipts."""


def ensure_deposit_schema(connection):
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS field_deposits (
            player_id INTEGER NOT NULL REFERENCES players(id),
            deposit_key TEXT NOT NULL,
            first_operation_id TEXT NOT NULL UNIQUE REFERENCES operations(operation_id),
            last_operation_id TEXT NOT NULL UNIQUE REFERENCES operations(operation_id),
            stock INTEGER NOT NULL CHECK(stock >= 0),
            regenerates_at TEXT NOT NULL,
            ready_at TEXT NOT NULL,
            maintenance_date TEXT NOT NULL,
            maintenance_used INTEGER NOT NULL CHECK(maintenance_used >= 0),
            snapshot_json TEXT NOT NULL,
            PRIMARY KEY(player_id, deposit_key)
        );
    """)
