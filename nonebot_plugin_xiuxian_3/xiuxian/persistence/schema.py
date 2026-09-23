"""SQLite schema owned by the persistence layer.

The schema is kept separate from transaction code so migrations and table
ownership can be reviewed without scanning feature implementations.
"""

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT NOT NULL UNIQUE,
    platform TEXT NOT NULL,
    platform_user_id TEXT NOT NULL,
    scene_id TEXT NOT NULL DEFAULT '',
    nickname TEXT NOT NULL DEFAULT '',
    dao_name TEXT NOT NULL DEFAULT '',
    stage TEXT NOT NULL CHECK (stage IN ('new_user', 'mortal', 'seeker', 'cultivator', 'suspended')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'deleted')),
    location_key TEXT NOT NULL DEFAULT 'xuantian.new_town',
    rule_version TEXT NOT NULL DEFAULT 'player-onboarding-v0.1.0',
    path_key TEXT,
    subprofession_key TEXT,
    qualification_json TEXT NOT NULL DEFAULT '{}',
    spirit_stones INTEGER NOT NULL DEFAULT 0 CHECK (spirit_stones >= 0),
    stamina INTEGER NOT NULL DEFAULT 0 CHECK (stamina >= 0),
    stamina_max INTEGER NOT NULL DEFAULT 0 CHECK (stamina_max >= 0),
    energy INTEGER NOT NULL DEFAULT 0 CHECK (energy >= 0),
    energy_max INTEGER NOT NULL DEFAULT 0 CHECK (energy_max >= 0),
    inventory_json TEXT NOT NULL DEFAULT '{}',
    intro_json TEXT NOT NULL DEFAULT '{}',
    selected_service TEXT,
    realm_key TEXT NOT NULL DEFAULT 'mortal',
    realm_layer INTEGER NOT NULL DEFAULT 0 CHECK (realm_layer >= 0),
    cultivation INTEGER NOT NULL DEFAULT 0 CHECK (cultivation >= 0),
    total_cultivation INTEGER NOT NULL DEFAULT 0 CHECK (total_cultivation >= 0),
    foundation_quality INTEGER NOT NULL DEFAULT 0 CHECK (foundation_quality >= 0),
    world_merit INTEGER NOT NULL DEFAULT 0 CHECK (world_merit >= 0),
    talent_points INTEGER NOT NULL DEFAULT 0 CHECK (talent_points >= 0),
    skill_insights INTEGER NOT NULL DEFAULT 0 CHECK (skill_insights >= 0),
    weakness_until TEXT,
    breakthrough_pity_bp INTEGER NOT NULL DEFAULT 0 CHECK (breakthrough_pity_bp >= 0),
    soul_power INTEGER NOT NULL DEFAULT 0 CHECK (soul_power >= 0),
    soul_power_max INTEGER NOT NULL DEFAULT 0 CHECK (soul_power_max >= 0),
    domain_charge INTEGER NOT NULL DEFAULT 0 CHECK (domain_charge >= 0),
    domain_charge_max INTEGER NOT NULL DEFAULT 0 CHECK (domain_charge_max >= 0),
    pollution INTEGER NOT NULL DEFAULT 0 CHECK (pollution >= 0),
    bloodline_stability INTEGER NOT NULL DEFAULT 0 CHECK (bloodline_stability >= 0),
    cross_realm_penalty_bp INTEGER NOT NULL DEFAULT 0 CHECK (cross_realm_penalty_bp >= 0),
    soul_fatigue_until TEXT,
    heart_demon_bonus_bp INTEGER NOT NULL DEFAULT 0 CHECK (heart_demon_bonus_bp >= 0),
    max_hp INTEGER NOT NULL DEFAULT 0 CHECK (max_hp >= 0),
    max_mp INTEGER NOT NULL DEFAULT 0 CHECK (max_mp >= 0),
    carry_capacity INTEGER NOT NULL DEFAULT 0 CHECK (carry_capacity >= 0),
    exploration_efficiency_bp INTEGER NOT NULL DEFAULT 0 CHECK (exploration_efficiency_bp >= 0),
    domain_key TEXT,
    domain_power INTEGER NOT NULL DEFAULT 0 CHECK (domain_power >= 0),
    realm_resistance_bp INTEGER NOT NULL DEFAULT 0 CHECK (realm_resistance_bp >= 0),
    domain_crack_until TEXT,
    initiative INTEGER NOT NULL DEFAULT 0 CHECK (initiative >= 0),
    faction_reputation_json TEXT NOT NULL DEFAULT '{}',
    domain_charge_reset_date TEXT,
    void_power INTEGER NOT NULL DEFAULT 0 CHECK (void_power >= 0),
    void_power_max INTEGER NOT NULL DEFAULT 0 CHECK (void_power_max >= 0),
    space_resistance_bp INTEGER NOT NULL DEFAULT 0 CHECK (space_resistance_bp >= 0),
    void_instability_until TEXT,
    void_route_count INTEGER NOT NULL DEFAULT 0 CHECK (void_route_count >= 0),
    void_anchor_capacity INTEGER NOT NULL DEFAULT 0 CHECK (void_anchor_capacity >= 0),
    void_power_reset_date TEXT,
    dao_fruit_progress INTEGER NOT NULL DEFAULT 0 CHECK (dao_fruit_progress >= 0),
    ascension_merit INTEGER NOT NULL DEFAULT 0 CHECK (ascension_merit >= 0),
    tribulation_debt INTEGER NOT NULL DEFAULT 0 CHECK (tribulation_debt >= 0),
    dao_fruit_key TEXT,
    endgame_status TEXT NOT NULL DEFAULT 'none',
    ending_key TEXT,
    sect_join_cooldown_until TEXT,
    durability_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (platform, platform_user_id)
);

CREATE TABLE IF NOT EXISTS operations (
    operation_id TEXT PRIMARY KEY,
    operation_name TEXT NOT NULL,
    player_id INTEGER NOT NULL REFERENCES players(id),
    request_hash TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_players_scene ON players(scene_id);
CREATE INDEX IF NOT EXISTS idx_operations_player ON operations(player_id);

CREATE TABLE IF NOT EXISTS endgame_endings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL UNIQUE REFERENCES players(id),
    ending_key TEXT NOT NULL CHECK (ending_key IN ('ascend', 'remain_in_world')),
    status TEXT NOT NULL CHECK (status IN ('ascended', 'remained_in_world')),
    fruit_key TEXT,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    operation_id TEXT NOT NULL UNIQUE,
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_endgame_endings_status
    ON endgame_endings(status, created_at);

CREATE TABLE IF NOT EXISTS cultivation_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    mode_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'settled', 'cancelled', 'expired')),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    stamina_cost INTEGER NOT NULL DEFAULT 0 CHECK (stamina_cost >= 0),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cultivation_sessions_player ON cultivation_sessions(player_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cultivation_sessions_active
    ON cultivation_sessions(player_id) WHERE status = 'running';

CREATE TABLE IF NOT EXISTS retreat_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    retreat_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'settled', 'expired')),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    energy_cost INTEGER NOT NULL DEFAULT 0 CHECK (energy_cost >= 0),
    item_cost_json TEXT NOT NULL DEFAULT '{}',
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_retreat_sessions_player
    ON retreat_sessions(player_id, retreat_key, starts_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_retreat_sessions_active
    ON retreat_sessions(player_id) WHERE status = 'running';

CREATE TABLE IF NOT EXISTS residences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    residence_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    residence_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'expired')),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    rent_cost INTEGER NOT NULL CHECK (rent_cost >= 0),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_residences_player ON residences(player_id, ends_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_residences_active ON residences(player_id) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS field_plots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plot_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    residence_id TEXT NOT NULL REFERENCES residences(residence_id),
    operation_id TEXT NOT NULL UNIQUE,
    crop_key TEXT,
    status TEXT NOT NULL CHECK (status IN ('growing', 'harvestable', 'harvested', 'withered')),
    planted_at TEXT NOT NULL,
    harvest_at TEXT NOT NULL,
    business_date TEXT NOT NULL,
    maintenance_count INTEGER NOT NULL DEFAULT 0 CHECK (maintenance_count >= 0),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_field_plots_player ON field_plots(player_id, business_date);
CREATE INDEX IF NOT EXISTS idx_field_plots_residence ON field_plots(residence_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_field_plots_active
    ON field_plots(residence_id) WHERE status IN ('growing', 'harvestable');

CREATE TABLE IF NOT EXISTS town_commissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    commission_id TEXT NOT NULL UNIQUE,
    commission_key TEXT NOT NULL,
    business_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('published', 'paused', 'expired')),
    stock_total INTEGER NOT NULL CHECK (stock_total >= 0),
    stock_remaining INTEGER NOT NULL CHECK (stock_remaining >= 0),
    starts_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (commission_key, business_date)
);

CREATE INDEX IF NOT EXISTS idx_town_commissions_date
    ON town_commissions(business_date, status);

CREATE TABLE IF NOT EXISTS town_commission_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL UNIQUE,
    commission_id TEXT NOT NULL REFERENCES town_commissions(commission_id),
    player_id INTEGER NOT NULL REFERENCES players(id),
    business_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('accepted', 'delivered', 'expired')),
    accept_operation_id TEXT NOT NULL UNIQUE,
    deliver_operation_id TEXT UNIQUE,
    accepted_at TEXT NOT NULL,
    delivered_at TEXT,
    result_json TEXT NOT NULL DEFAULT '{}',
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (player_id, commission_id)
);

CREATE INDEX IF NOT EXISTS idx_town_commission_claims_player
    ON town_commission_claims(player_id, business_date, status);

CREATE TABLE IF NOT EXISTS livelihood_service_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL UNIQUE,
    publish_operation_id TEXT NOT NULL UNIQUE,
    accept_operation_id TEXT UNIQUE,
    settle_operation_id TEXT UNIQUE,
    publisher_id INTEGER NOT NULL REFERENCES players(id),
    provider_id INTEGER REFERENCES players(id),
    service_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('published', 'accepted', 'delivered', 'failed', 'expired', 'cancelled')),
    reward_stones INTEGER NOT NULL CHECK (reward_stones > 0),
    starts_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    accepted_at TEXT,
    settled_at TEXT,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_livelihood_service_orders_publisher
    ON livelihood_service_orders(publisher_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_livelihood_service_orders_provider
    ON livelihood_service_orders(provider_id, service_key, accepted_at);

CREATE TABLE IF NOT EXISTS livelihood_trade_routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    settle_operation_id TEXT UNIQUE,
    route_key TEXT NOT NULL,
    business_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('in_transit', 'settled', 'failed', 'expired')),
    source_location TEXT NOT NULL,
    destination_location TEXT NOT NULL,
    cargo_json TEXT NOT NULL DEFAULT '{}',
    cargo_value INTEGER NOT NULL CHECK (cargo_value > 0),
    starts_at TEXT NOT NULL,
    arrives_at TEXT NOT NULL,
    settled_at TEXT,
    stamina_cost INTEGER NOT NULL CHECK (stamina_cost >= 0),
    reward_stones INTEGER NOT NULL CHECK (reward_stones >= 0),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_livelihood_trade_routes_player
    ON livelihood_trade_routes(player_id, business_date, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_livelihood_trade_routes_active
    ON livelihood_trade_routes(player_id) WHERE status = 'in_transit';

CREATE TABLE IF NOT EXISTS sects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sect_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE,
    motto TEXT NOT NULL DEFAULT '',
    leader_id INTEGER NOT NULL REFERENCES players(id),
    status TEXT NOT NULL CHECK (status IN ('active', 'dissolving', 'dissolved')),
    max_members INTEGER NOT NULL CHECK (max_members > 0),
    warehouse_capacity INTEGER NOT NULL CHECK (warehouse_capacity >= 0),
    construction INTEGER NOT NULL DEFAULT 0 CHECK (construction >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sects_status ON sects(status, created_at);

CREATE TABLE IF NOT EXISTS sect_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sect_id TEXT NOT NULL REFERENCES sects(sect_id),
    player_id INTEGER NOT NULL REFERENCES players(id),
    role TEXT NOT NULL CHECK (role IN ('member', 'deacon', 'elder', 'vice_leader', 'leader')),
    status TEXT NOT NULL CHECK (status IN ('active', 'left', 'kicked')),
    contribution INTEGER NOT NULL DEFAULT 0 CHECK (contribution >= 0),
    joined_at TEXT NOT NULL,
    left_at TEXT,
    last_action_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sect_members_sect ON sect_members(sect_id, status, role);
CREATE INDEX IF NOT EXISTS idx_sect_members_player ON sect_members(player_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sect_members_active_player
    ON sect_members(player_id) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS sect_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id TEXT NOT NULL UNIQUE,
    sect_id TEXT NOT NULL REFERENCES sects(sect_id),
    applicant_id INTEGER NOT NULL REFERENCES players(id),
    status TEXT NOT NULL CHECK (status IN ('pending', 'accepted', 'rejected', 'expired', 'withdrawn')),
    reason TEXT NOT NULL DEFAULT '',
    review_reason TEXT NOT NULL DEFAULT '',
    reviewer_id INTEGER REFERENCES players(id),
    apply_operation_id TEXT NOT NULL UNIQUE,
    review_operation_id TEXT UNIQUE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sect_applications_sect ON sect_applications(sect_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_sect_applications_applicant ON sect_applications(applicant_id, status, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sect_applications_pending
    ON sect_applications(sect_id, applicant_id) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS constitution_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL UNIQUE REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    constitution_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('selected')),
    selected_at TEXT NOT NULL,
    last_reshaped_at TEXT,
    reshape_count INTEGER NOT NULL DEFAULT 0 CHECK (reshape_count >= 0),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_constitution_profiles_player
    ON constitution_profiles(player_id, updated_at);

CREATE TABLE IF NOT EXISTS talent_node_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    node_key TEXT NOT NULL,
    tree_key TEXT NOT NULL,
    tier INTEGER NOT NULL CHECK (tier BETWEEN 1 AND 5),
    status TEXT NOT NULL CHECK (status IN ('learned')),
    cost_points INTEGER NOT NULL CHECK (cost_points >= 0),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    unlocked_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (player_id, node_key)
);

CREATE INDEX IF NOT EXISTS idx_talent_node_states_player
    ON talent_node_states(player_id, tree_key, tier);
CREATE UNIQUE INDEX IF NOT EXISTS idx_talent_node_states_one_per_tier
    ON talent_node_states(player_id, tree_key, tier) WHERE status = 'learned';

CREATE TABLE IF NOT EXISTS talent_point_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    delta INTEGER NOT NULL CHECK (delta <> 0),
    balance_before INTEGER NOT NULL CHECK (balance_before >= 0),
    balance_after INTEGER NOT NULL CHECK (balance_after >= 0),
    reason TEXT NOT NULL,
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_talent_point_events_player
    ON talent_point_events(player_id, created_at);

CREATE TABLE IF NOT EXISTS skill_masteries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mastery_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    skill_key TEXT NOT NULL,
    path_key TEXT,
    level INTEGER NOT NULL CHECK (level BETWEEN 1 AND 3),
    max_level INTEGER NOT NULL CHECK (max_level = 3),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    trained_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (player_id, skill_key)
);

CREATE INDEX IF NOT EXISTS idx_skill_masteries_player
    ON skill_masteries(player_id, skill_key);

CREATE TABLE IF NOT EXISTS skill_insight_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    delta INTEGER NOT NULL CHECK (delta <> 0),
    balance_before INTEGER NOT NULL CHECK (balance_before >= 0),
    balance_after INTEGER NOT NULL CHECK (balance_after >= 0),
    reason TEXT NOT NULL,
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_skill_insight_events_player
    ON skill_insight_events(player_id, created_at);

CREATE TABLE IF NOT EXISTS equipment_instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    item_key TEXT NOT NULL,
    label TEXT NOT NULL,
    slot TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'broken', 'archived')),
    durability_bp INTEGER NOT NULL CHECK (durability_bp >= 0),
    temper_level INTEGER NOT NULL CHECK (temper_level BETWEEN 0 AND 3),
    max_temper_level INTEGER NOT NULL CHECK (max_temper_level = 3),
    affixes_json TEXT NOT NULL DEFAULT '{}',
    refinement_failure_streak INTEGER NOT NULL DEFAULT 0 CHECK (refinement_failure_streak >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (player_id, instance_id)
);

CREATE INDEX IF NOT EXISTS idx_equipment_instances_player
    ON equipment_instances(player_id, item_key, status);

CREATE TABLE IF NOT EXISTS equipment_tempering_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    equipment_id INTEGER NOT NULL REFERENCES equipment_instances(id),
    operation_id TEXT NOT NULL UNIQUE,
    from_level INTEGER NOT NULL CHECK (from_level >= 0),
    to_level INTEGER NOT NULL CHECK (to_level >= 1),
    success INTEGER NOT NULL CHECK (success IN (0, 1)),
    roll_bp INTEGER NOT NULL CHECK (roll_bp BETWEEN 0 AND 9999),
    success_bp INTEGER NOT NULL CHECK (success_bp BETWEEN 0 AND 10000),
    material_key TEXT NOT NULL,
    material_spent INTEGER NOT NULL CHECK (material_spent >= 0),
    spirit_stones_spent INTEGER NOT NULL CHECK (spirit_stones_spent >= 0),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_equipment_tempering_events_player
    ON equipment_tempering_events(player_id, created_at);

CREATE TABLE IF NOT EXISTS equipment_refinement_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    equipment_id INTEGER NOT NULL REFERENCES equipment_instances(id),
    operation_id TEXT NOT NULL UNIQUE,
    success INTEGER NOT NULL CHECK (success IN (0, 1)),
    roll_bp INTEGER NOT NULL CHECK (roll_bp BETWEEN 0 AND 9999),
    success_bp INTEGER NOT NULL CHECK (success_bp BETWEEN 0 AND 10000),
    material_key TEXT NOT NULL,
    material_spent INTEGER NOT NULL CHECK (material_spent >= 0),
    spirit_stones_spent INTEGER NOT NULL CHECK (spirit_stones_spent >= 0),
    old_affixes_json TEXT NOT NULL DEFAULT '{}',
    new_affixes_json TEXT NOT NULL DEFAULT '{}',
    failure_streak_before INTEGER NOT NULL CHECK (failure_streak_before >= 0),
    failure_streak_after INTEGER NOT NULL CHECK (failure_streak_after >= 0),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_equipment_refinement_events_player
    ON equipment_refinement_events(player_id, created_at);

CREATE TABLE IF NOT EXISTS production_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    recipe_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('processing', 'completed', 'failed', 'cancelled', 'expired')),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    energy_cost INTEGER NOT NULL DEFAULT 0 CHECK (energy_cost >= 0),
    currency_cost INTEGER NOT NULL DEFAULT 0 CHECK (currency_cost >= 0),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_production_orders_player ON production_orders(player_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_production_orders_active
    ON production_orders(player_id) WHERE status = 'processing';

CREATE TABLE IF NOT EXISTS breakthrough_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    target_realm TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('preparing', 'succeeded', 'failed', 'expired')),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_breakthrough_sessions_player ON breakthrough_sessions(player_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_breakthrough_sessions_active
    ON breakthrough_sessions(player_id) WHERE status = 'preparing';

CREATE TABLE IF NOT EXISTS heart_demon_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    breakthrough_session_id INTEGER NOT NULL REFERENCES breakthrough_sessions(id),
    operation_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('pending', 'resolved')),
    choice_key TEXT,
    expires_at TEXT NOT NULL,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_heart_demon_sessions_player
    ON heart_demon_sessions(player_id, status);

CREATE TABLE IF NOT EXISTS domain_selection_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    domain_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'confirmed', 'cancelled', 'expired')),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_domain_selection_sessions_player
    ON domain_selection_sessions(player_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_domain_selection_sessions_active
    ON domain_selection_sessions(player_id) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS travel_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    source_location TEXT NOT NULL,
    destination TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'arrived', 'cancelled', 'expired')),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    stamina_cost INTEGER NOT NULL DEFAULT 0 CHECK (stamina_cost >= 0),
    currency_cost INTEGER NOT NULL DEFAULT 0 CHECK (currency_cost >= 0),
    pass_key TEXT,
    pass_quantity INTEGER NOT NULL DEFAULT 0 CHECK (pass_quantity >= 0),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_travel_sessions_player ON travel_sessions(player_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_travel_sessions_active
    ON travel_sessions(player_id) WHERE status = 'running';

CREATE TABLE IF NOT EXISTS exploration_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exploration_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    mode_key TEXT NOT NULL,
    location_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('created', 'running', 'settled', 'cancelled', 'expired', 'combat_pending')),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    stamina_cost INTEGER NOT NULL DEFAULT 0 CHECK (stamina_cost >= 0),
    daily_limit INTEGER NOT NULL DEFAULT 0 CHECK (daily_limit >= 0),
    business_date TEXT NOT NULL,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_exploration_sessions_player ON exploration_sessions(player_id);
CREATE INDEX IF NOT EXISTS idx_exploration_sessions_quota
    ON exploration_sessions(player_id, mode_key, business_date);
CREATE UNIQUE INDEX IF NOT EXISTS idx_exploration_sessions_active
    ON exploration_sessions(player_id) WHERE status IN ('created', 'running', 'combat_pending');

CREATE TABLE IF NOT EXISTS player_reputations (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    local_json TEXT NOT NULL DEFAULT '{}',
    service_reputation INTEGER NOT NULL DEFAULT 0 CHECK (service_reputation >= 0 AND service_reputation <= 100),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bounty_offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    bounty_key TEXT NOT NULL,
    business_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('accepted', 'completed', 'claimed', 'expired')),
    accepted_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (player_id, business_date)
);

CREATE INDEX IF NOT EXISTS idx_bounty_offers_player ON bounty_offers(player_id, business_date);
CREATE INDEX IF NOT EXISTS idx_bounty_offers_status ON bounty_offers(player_id, status);

CREATE TABLE IF NOT EXISTS routine_checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    activity_key TEXT NOT NULL,
    target_date TEXT NOT NULL,
    claim_kind TEXT NOT NULL CHECK (claim_kind IN ('daily', 'makeup')),
    month_key TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('claimed', 'expired')),
    cost_json TEXT NOT NULL DEFAULT '{}',
    reward_json TEXT NOT NULL DEFAULT '{}',
    streak_before INTEGER NOT NULL DEFAULT 0 CHECK (streak_before >= 0),
    streak_after INTEGER NOT NULL DEFAULT 0 CHECK (streak_after >= 0),
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    settled_at TEXT NOT NULL,
    UNIQUE (player_id, target_date)
);

CREATE INDEX IF NOT EXISTS idx_routine_checkins_player_date
    ON routine_checkins(player_id, target_date);
CREATE INDEX IF NOT EXISTS idx_routine_checkins_makeup_month
    ON routine_checkins(player_id, claim_kind, month_key);

CREATE TABLE IF NOT EXISTS spirit_trees (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    cycle_no INTEGER NOT NULL DEFAULT 1 CHECK (cycle_no >= 1),
    water_count INTEGER NOT NULL DEFAULT 0 CHECK (water_count >= 0 AND water_count <= 7),
    last_water_date TEXT,
    cycle_started_at TEXT,
    cooldown_until TEXT,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS spirit_tree_waterings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    cycle_no INTEGER NOT NULL CHECK (cycle_no >= 1),
    business_date TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE (player_id, cycle_no, business_date)
);

CREATE TABLE IF NOT EXISTS spirit_tree_harvests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    cycle_no INTEGER NOT NULL CHECK (cycle_no >= 1),
    operation_id TEXT NOT NULL UNIQUE,
    pool_key TEXT NOT NULL,
    seed TEXT NOT NULL,
    reward_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE (player_id, cycle_no)
);

CREATE INDEX IF NOT EXISTS idx_spirit_tree_waterings_player
    ON spirit_tree_waterings(player_id, cycle_no, business_date);

CREATE TABLE IF NOT EXISTS activity_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    event_key TEXT NOT NULL,
    source_operation_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (player_id, event_key, source_operation_id)
);

CREATE INDEX IF NOT EXISTS idx_activity_events_player_key
    ON activity_events(player_id, event_key, occurred_at);

CREATE TABLE IF NOT EXISTS seven_day_campaigns (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    start_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'completed', 'closed')),
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seven_day_goal_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    day_number INTEGER NOT NULL CHECK (day_number BETWEEN 1 AND 7),
    goal_key TEXT NOT NULL,
    target_date TEXT NOT NULL,
    source_operation_id TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    reward_json TEXT NOT NULL DEFAULT '{}',
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (player_id, day_number),
    UNIQUE (player_id, source_operation_id)
);

CREATE INDEX IF NOT EXISTS idx_seven_day_claims_player
    ON seven_day_goal_claims(player_id, day_number);

CREATE TABLE IF NOT EXISTS honor_titles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    title_key TEXT NOT NULL,
    source_operation_id TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    UNIQUE (player_id, title_key),
    UNIQUE (player_id, source_operation_id)
);

CREATE INDEX IF NOT EXISTS idx_honor_titles_player
    ON honor_titles(player_id, acquired_at);

CREATE TABLE IF NOT EXISTS honor_states (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    equipped_title_key TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS achievement_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    achievement_key TEXT NOT NULL,
    source_operation_id TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    reward_json TEXT NOT NULL DEFAULT '{}',
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (player_id, achievement_key),
    UNIQUE (player_id, source_operation_id)
);

CREATE INDEX IF NOT EXISTS idx_achievement_claims_player
    ON achievement_claims(player_id, created_at);

CREATE TABLE IF NOT EXISTS redemption_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code_key TEXT NOT NULL UNIQUE,
    code_hash TEXT NOT NULL UNIQUE,
    max_claims INTEGER NOT NULL CHECK (max_claims > 0),
    claimed_count INTEGER NOT NULL DEFAULT 0 CHECK (claimed_count >= 0),
    starts_on TEXT,
    ends_on TEXT,
    status TEXT NOT NULL CHECK (status IN ('active', 'revoked')),
    reward_json TEXT NOT NULL DEFAULT '{}',
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS redemption_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    code_id INTEGER NOT NULL REFERENCES redemption_codes(id),
    code_key TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    reward_json TEXT NOT NULL DEFAULT '{}',
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (player_id, code_id)
);

CREATE INDEX IF NOT EXISTS idx_redemption_claims_player
    ON redemption_claims(player_id, created_at);

CREATE TABLE IF NOT EXISTS fate_pools (
    player_id INTEGER NOT NULL REFERENCES players(id),
    pool_key TEXT NOT NULL,
    pity_count INTEGER NOT NULL DEFAULT 0 CHECK (pity_count >= 0 AND pity_count < 10),
    total_draws INTEGER NOT NULL DEFAULT 0 CHECK (total_draws >= 0),
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (player_id, pool_key)
);

CREATE TABLE IF NOT EXISTS fate_rolls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    pool_key TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    draw_count INTEGER NOT NULL CHECK (draw_count IN (1, 10)),
    cost_kind TEXT NOT NULL CHECK (cost_kind IN ('spirit_stones', 'ticket')),
    cost_quantity INTEGER NOT NULL CHECK (cost_quantity > 0),
    pity_before INTEGER NOT NULL CHECK (pity_before >= 0 AND pity_before < 10),
    pity_after INTEGER NOT NULL CHECK (pity_after >= 0 AND pity_after < 10),
    seed_hash TEXT NOT NULL,
    reward_json TEXT NOT NULL DEFAULT '{}',
    draws_json TEXT NOT NULL DEFAULT '[]',
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fate_rolls_player
    ON fate_rolls(player_id, pool_key, created_at);

CREATE TABLE IF NOT EXISTS wayfaring_passes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    pass_key TEXT NOT NULL,
    cycle_start TEXT NOT NULL,
    cycle_end TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'completed', 'closed')),
    total_points INTEGER NOT NULL DEFAULT 0 CHECK (total_points >= 0),
    daily_date TEXT NOT NULL,
    daily_points INTEGER NOT NULL DEFAULT 0 CHECK (daily_points >= 0),
    week_start TEXT NOT NULL,
    weekly_points INTEGER NOT NULL DEFAULT 0 CHECK (weekly_points >= 0),
    claimed_free_json TEXT NOT NULL DEFAULT '[]',
    claimed_paid_json TEXT NOT NULL DEFAULT '[]',
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (player_id, pass_key, cycle_start)
);

CREATE INDEX IF NOT EXISTS idx_wayfaring_passes_player
    ON wayfaring_passes(player_id, pass_key, cycle_start);

CREATE TABLE IF NOT EXISTS wayfaring_point_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    pass_id INTEGER NOT NULL REFERENCES wayfaring_passes(id),
    source_key TEXT NOT NULL,
    source_operation_id TEXT NOT NULL,
    business_date TEXT NOT NULL,
    week_start TEXT NOT NULL,
    points INTEGER NOT NULL CHECK (points >= 0),
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (player_id, pass_id, source_operation_id)
);

CREATE INDEX IF NOT EXISTS idx_wayfaring_point_events_pass
    ON wayfaring_point_events(pass_id, business_date, week_start);

CREATE TABLE IF NOT EXISTS wayfaring_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    pass_id INTEGER NOT NULL REFERENCES wayfaring_passes(id),
    level INTEGER NOT NULL CHECK (level BETWEEN 1 AND 30),
    track TEXT NOT NULL CHECK (track IN ('free', 'paid')),
    operation_id TEXT NOT NULL UNIQUE,
    reward_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE (player_id, pass_id, level, track)
);

CREATE INDEX IF NOT EXISTS idx_wayfaring_claims_player
    ON wayfaring_claims(player_id, pass_id, level);

CREATE TABLE IF NOT EXISTS dao_contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    contract_key TEXT NOT NULL,
    receipt_id TEXT NOT NULL UNIQUE,
    receipt_hash TEXT NOT NULL UNIQUE,
    subject TEXT NOT NULL,
    starts_on TEXT NOT NULL,
    ends_on TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'revoked', 'expired')),
    revoke_reason TEXT,
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (player_id, contract_key, starts_on)
);

CREATE INDEX IF NOT EXISTS idx_dao_contracts_player
    ON dao_contracts(player_id, status, ends_on);

CREATE TABLE IF NOT EXISTS dao_contract_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    contract_id INTEGER NOT NULL REFERENCES dao_contracts(id),
    contract_key TEXT NOT NULL,
    business_date TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    reward_json TEXT NOT NULL DEFAULT '{}',
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (contract_id, business_date)
);

CREATE INDEX IF NOT EXISTS idx_dao_contract_claims_player
    ON dao_contract_claims(player_id, business_date);

CREATE TABLE IF NOT EXISTS mainline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    story_key TEXT NOT NULL,
    chapter INTEGER NOT NULL CHECK (chapter >= 1),
    stage INTEGER NOT NULL CHECK (stage >= 1),
    stage_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('locked', 'available', 'running', 'cleared', 'reward_pending', 'claimed')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    first_clear_claimed INTEGER NOT NULL DEFAULT 0 CHECK (first_clear_claimed IN (0, 1)),
    first_clear_key TEXT NOT NULL UNIQUE,
    start_operation_id TEXT,
    claim_operation_id TEXT,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (player_id, story_key, stage_key)
);

CREATE INDEX IF NOT EXISTS idx_mainline_runs_player
    ON mainline_runs(player_id, story_key, chapter, stage);
CREATE INDEX IF NOT EXISTS idx_mainline_runs_status
    ON mainline_runs(player_id, status);

CREATE TABLE IF NOT EXISTS void_route_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    route_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'settled', 'failed')),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    anchor_cost INTEGER NOT NULL CHECK (anchor_cost >= 1),
    stamina_cost INTEGER NOT NULL CHECK (stamina_cost >= 0),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_void_route_sessions_player ON void_route_sessions(player_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_void_route_sessions_active
    ON void_route_sessions(player_id) WHERE status = 'running';

CREATE TABLE IF NOT EXISTS tribulation_trial_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    trial_key TEXT NOT NULL,
    choice_key TEXT,
    status TEXT NOT NULL CHECK (status IN ('preparing', 'succeeded', 'failed', 'expired')),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tribulation_trial_sessions_player
    ON tribulation_trial_sessions(player_id, trial_key, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tribulation_trial_sessions_active
    ON tribulation_trial_sessions(player_id) WHERE status = 'preparing';

CREATE TABLE IF NOT EXISTS endgame_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    session_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('preparing', 'succeeded', 'failed')),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_endgame_sessions_player
    ON endgame_sessions(player_id, session_type, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_endgame_sessions_active
    ON endgame_sessions(player_id) WHERE status = 'preparing';


"""
