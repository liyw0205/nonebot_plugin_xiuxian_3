ALTER TABLE players ADD COLUMN energy INTEGER NOT NULL DEFAULT 0 CHECK (energy >= 0);
ALTER TABLE players ADD COLUMN inventory_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE players ADD COLUMN qualification_snapshot_id TEXT;

CREATE TABLE qualification_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    player_id TEXT NOT NULL UNIQUE,
    spirit_root TEXT NOT NULL,
    body INTEGER NOT NULL CHECK (body BETWEEN 5 AND 15),
    spirit INTEGER NOT NULL CHECK (spirit BETWEEN 5 AND 15),
    insight INTEGER NOT NULL CHECK (insight BETWEEN 5 AND 15),
    root INTEGER NOT NULL CHECK (root BETWEEN 5 AND 15),
    agility INTEGER NOT NULL CHECK (agility BETWEEN 5 AND 15),
    fortune INTEGER NOT NULL CHECK (fortune BETWEEN 5 AND 15),
    random_pool TEXT NOT NULL,
    result_digest TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    rule_version TEXT NOT NULL,
    FOREIGN KEY (player_id) REFERENCES players(player_id)
);