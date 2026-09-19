ALTER TABLE players ADD COLUMN realm_key TEXT NOT NULL DEFAULT 'mortal';
ALTER TABLE players ADD COLUMN realm_layer INTEGER NOT NULL DEFAULT 0 CHECK (realm_layer BETWEEN 0 AND 10);
ALTER TABLE players ADD COLUMN path_key TEXT;
ALTER TABLE players ADD COLUMN subprofession_key TEXT;
ALTER TABLE players ADD COLUMN known_skills_json TEXT NOT NULL DEFAULT '[]';