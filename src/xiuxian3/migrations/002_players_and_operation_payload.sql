ALTER TABLE operation_ledger ADD COLUMN result_payload TEXT;

CREATE TABLE players (
    player_id TEXT PRIMARY KEY,
    external_id TEXT NOT NULL UNIQUE,
    nickname TEXT NOT NULL,
    realm TEXT NOT NULL,
    level INTEGER NOT NULL CHECK (level >= 1),
    cultivation INTEGER NOT NULL CHECK (cultivation >= 0),
    spirit_stones INTEGER NOT NULL CHECK (spirit_stones >= 0),
    stamina INTEGER NOT NULL CHECK (stamina >= 0),
    status TEXT NOT NULL CHECK (status IN ('active', 'disabled', 'deleted'))
);