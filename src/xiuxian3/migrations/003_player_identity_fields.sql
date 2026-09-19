ALTER TABLE players ADD COLUMN platform TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE players ADD COLUMN platform_user_id TEXT NOT NULL DEFAULT '';
ALTER TABLE players ADD COLUMN scene TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE players ADD COLUMN stage TEXT NOT NULL DEFAULT 'mortal';
ALTER TABLE players ADD COLUMN location_key TEXT NOT NULL DEFAULT 'xuantian.new_town';

CREATE UNIQUE INDEX players_platform_identity_idx
    ON players(platform, platform_user_id)
    WHERE platform_user_id <> '';