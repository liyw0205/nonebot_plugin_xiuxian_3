"""Rules for the domain-front event and season."""

from __future__ import annotations


import hashlib
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content
from ..rewards.rules import RewardGrant, local_reputation_maximum, reward_definition, reward_grant_from_snapshot, reward_totals


EVENT_KEY = "event.domain_front"
LOCATION_KEY = "xuantian.domain_front"
SEASON_KEY = "season.domain_war"
ACTION_VALUES = {"战斗": "battle", "领域战": "battle", "占点": "point", "据点": "point"}


@dataclass(frozen=True, slots=True)
class DomainFrontDefinition:
    event_key: str
    name: str
    desc: str
    status: str
    location_key: str
    required_realm_key: str
    required_realm_layer: int
    required_realm_rank: int
    activity_hours: int
    anchor_hour: int
    round_minutes: int
    claim_days: int
    participant_cap: int
    join_stamina_cost: int
    sect_level_min: int
    battle_contribution: int
    point_contribution_per_minute: int
    point_minutes_min: int
    point_minutes_max: int
    target_quantity: int
    personal_claim_threshold: int
    reward_key: str
    reward: RewardGrant
    reward_name: str
    reward_desc: str
    reward_local_reputation_maximums: tuple[tuple[str, int], ...]
    codex_entry_key: str

    def snapshot(self) -> dict[str, Any]:
        return {
            "event_key": self.event_key,
            "name": self.name,
            "desc": self.desc,
            "location_key": self.location_key,
            "required_realm_key": self.required_realm_key,
            "required_realm_layer": self.required_realm_layer,
            "required_realm_rank": self.required_realm_rank,
            "activity_hours": self.activity_hours,
            "anchor_hour": self.anchor_hour,
            "round_minutes": self.round_minutes,
            "claim_days": self.claim_days,
            "participant_cap": self.participant_cap,
            "join_stamina_cost": self.join_stamina_cost,
            "sect_level_min": self.sect_level_min,
            "battle_contribution": self.battle_contribution,
            "point_contribution_per_minute": self.point_contribution_per_minute,
            "point_minutes_min": self.point_minutes_min,
            "point_minutes_max": self.point_minutes_max,
            "target_quantity": self.target_quantity,
            "personal_claim_threshold": self.personal_claim_threshold,
            "reward_key": self.reward_key,
            "reward": self.reward.snapshot(),
            "reward_name": self.reward_name,
            "reward_desc": self.reward_desc,
            "reward_local_reputation_maximums": dict(self.reward_local_reputation_maximums),
            "codex_entry_key": self.codex_entry_key,
        }


@dataclass(frozen=True, slots=True)
class DomainWarSeasonDefinition:
    season_key: str
    name: str
    desc: str
    anchor: datetime
    duration_days: int
    claim_days: int
    rank_limit: int
    domain_multiplier: int
    sect_multiplier: int
    production_multiplier: int
    production_recipe_key_prefix: str
    production_snapshot_realm_key: str
    score_order: str
    achieved_at_order: str
    identity_tiebreak: str
    rank_rewards: tuple[tuple[int, int, str, RewardGrant, str, str, tuple[tuple[str, int], ...]], ...]
    fragment_item_key: str
    fragment_quantity: int
    reward_item_key: str
    reward_quantity: int

    def reward_for_rank(self, rank: int) -> dict[str, int]:
        for minimum, maximum, _key, reward, _name, _desc, _caps in self.rank_rewards:
            if minimum <= rank <= maximum:
                return reward_totals(reward)
        return {}

    def snapshot(self) -> dict[str, Any]:
        return {
            "season_key": self.season_key,
            "name": self.name,
            "desc": self.desc,
            "anchor": self.anchor.isoformat(),
            "duration_days": self.duration_days,
            "claim_days": self.claim_days,
            "rank_limit": self.rank_limit,
            "score_sources": {
                "domain_contribution": {"multiplier": self.domain_multiplier},
                "sect_contribution": {"multiplier": self.sect_multiplier},
                "soul_transformation_production": {"multiplier": self.production_multiplier, "recipe_key_prefix": self.production_recipe_key_prefix, "snapshot_realm_key": self.production_snapshot_realm_key},
            },
            "ranking": {"score_order": self.score_order, "achieved_at_order": self.achieved_at_order, "identity_tiebreak": self.identity_tiebreak},
            "rank_rewards": [
                {"min_rank": minimum, "max_rank": maximum, "reward_key": key, "reward": reward.snapshot(), "reward_name": name, "reward_desc": desc, "local_reputation_maximums": dict(caps)}
                for minimum, maximum, key, reward, name, desc, caps in self.rank_rewards
            ],
            "redemption": {
                "fragment_item_key": self.fragment_item_key,
                "fragment_quantity": self.fragment_quantity,
                "reward_item_key": self.reward_item_key,
                "reward_quantity": self.reward_quantity,
            },
        }


def _positive(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"domain front {field} must be a positive integer")
    return value


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"domain front {field} must be a non-empty string")
    return value.strip()


def _utc_midnight(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_required_text(value, field))
    except ValueError as exc:
        raise ContentError(f"{field} is invalid") from exc
    if parsed.tzinfo is None:
        raise ContentError(f"{field} must include a UTC offset")
    parsed = parsed.astimezone(timezone.utc)
    if parsed.hour or parsed.minute or parsed.second or parsed.microsecond:
        raise ContentError(f"{field} must align to UTC midnight")
    return parsed


def _reward_caps(grant: RewardGrant, content: ContentBundle) -> tuple[tuple[str, int], ...]:
    if grant.set_values:
        raise ContentError("domain-front rewards cannot set player values directly")
    return tuple(sorted((key, local_reputation_maximum(key, content)) for key in grant.local_reputation))


def _snapshot_reward_caps(value: Any, grant: RewardGrant, field: str) -> tuple[tuple[str, int], ...]:
    if grant.set_values:
        raise ContentError("domain-front rewards cannot set player values directly")
    if not isinstance(value, dict) or set(value) != set(grant.local_reputation):
        raise ContentError(f"{field} does not match reward local reputation")
    return tuple(sorted((str(key), _positive(maximum, f"{field} {key}")) for key, maximum in value.items()))


def domain_front_definition(content: ContentBundle | None = None) -> DomainFrontDefinition:
    bundle = content or bundled_content()
    try:
        row = bundle.require("event", EVENT_KEY, include_locked=False)
    except KeyError as exc:
        raise ContentError(f"domain front event is not active: {EVENT_KEY}") from exc
    expected_fields = {"name", "desc", "status", "location_key", "requirements", "schedule", "participation", "contribution", "global_goal", "personal_claim_threshold", "reward_key", "codex_entry_key", "key"}
    if set(row) != expected_fields:
        raise ContentError("domain front event has missing or unknown fields")
    name = _required_text(row["name"], "name")
    desc = _required_text(row["desc"], "desc")
    location_key = _required_text(row["location_key"], "location_key")
    if not bundle.has("location", location_key, include_locked=False):
        raise ContentError(f"domain front references inactive location: {location_key}")
    requirements = row["requirements"]
    if not isinstance(requirements, list) or len(requirements) != 1 or not isinstance(requirements[0], dict):
        raise ContentError("domain front requirements must contain one realm requirement")
    requirement = requirements[0]
    if set(requirement) != {"type", "realm_key", "min_layer"} or requirement.get("type") != "realm":
        raise ContentError("domain front realm requirement is invalid")
    realm_key = _required_text(requirement.get("realm_key"), "required realm key")
    layer = _positive(requirement.get("min_layer"), "required realm layer")
    realm = bundle.get("realm", realm_key, include_locked=False)
    if realm is None or not isinstance(realm.get("rank"), int):
        raise ContentError(f"domain front references inactive realm: {realm_key}")
    if layer < int(realm.get("layer_min", 1)) or layer > int(realm.get("layer_max", layer)):
        raise ContentError("domain front realm layer is outside realm bounds")
    schedule = row["schedule"]
    participation = row["participation"]
    contribution = row["contribution"]
    if not isinstance(schedule, dict) or set(schedule) != {"activity_hours", "anchor_hour", "round_minutes", "claim_days"}:
        raise ContentError("domain front schedule is invalid")
    if not isinstance(participation, dict) or set(participation) != {"participant_cap", "join_stamina_cost", "sect_level_min"}:
        raise ContentError("domain front participation is invalid")
    if not isinstance(contribution, dict) or set(contribution) != {"battle", "point_per_minute", "point_minutes_min", "point_minutes_max"}:
        raise ContentError("domain front contribution is invalid")
    activity_hours = _positive(schedule["activity_hours"], "activity_hours")
    anchor_hour = schedule["anchor_hour"]
    if isinstance(anchor_hour, bool) or not isinstance(anchor_hour, int) or not 0 <= anchor_hour <= 23:
        raise ContentError("domain front anchor_hour must be between 0 and 23")
    round_minutes = _positive(schedule["round_minutes"], "round_minutes")
    claim_days = _positive(schedule["claim_days"], "claim_days")
    if 24 % activity_hours != 0 or activity_hours * 60 % round_minutes != 0:
        raise ContentError("domain front schedule must partition the UTC day into complete rounds")
    participant_cap = _positive(participation["participant_cap"], "participant_cap")
    join_cost = _positive(participation["join_stamina_cost"], "join_stamina_cost")
    sect_level_min = _positive(participation["sect_level_min"], "sect_level_min")
    battle = _positive(contribution["battle"], "battle contribution")
    point = _positive(contribution["point_per_minute"], "point contribution")
    point_min = _positive(contribution["point_minutes_min"], "point minimum")
    point_max = _positive(contribution["point_minutes_max"], "point maximum")
    if point_min > point_max:
        raise ContentError("domain front point minute bounds are invalid")
    target = _positive(row["global_goal"], "global_goal")
    personal = _positive(row["personal_claim_threshold"], "personal_claim_threshold")
    reward_key = _required_text(row["reward_key"], "reward_key")
    reward = reward_definition(reward_key, bundle, operation="event.domain_front.claim")
    reward_caps = _reward_caps(reward, bundle)
    codex_key = _required_text(row["codex_entry_key"], "codex_entry_key")
    if not bundle.has("codex_entry", codex_key, include_locked=False):
        raise ContentError(f"domain front references inactive codex entry: {codex_key}")
    reward_row = bundle.require("reward", reward_key, include_locked=False)
    return DomainFrontDefinition(EVENT_KEY, name, desc, str(row["status"]), location_key, realm_key, layer, int(realm["rank"]), activity_hours, anchor_hour, round_minutes, claim_days, participant_cap, join_cost, sect_level_min, battle, point, point_min, point_max, target, personal, reward_key, reward, _required_text(reward_row.get("name"), "reward name"), _required_text(reward_row.get("desc"), "reward desc"), reward_caps, codex_key)


def domain_war_season_definition(content: ContentBundle | None = None) -> DomainWarSeasonDefinition:
    bundle = content or bundled_content()
    try:
        row = bundle.require("season", SEASON_KEY, include_locked=False)
    except KeyError as exc:
        raise ContentError(f"domain war season is not active: {SEASON_KEY}") from exc
    required = {"key", "name", "desc", "status", "anchor", "duration_days", "claim_days", "rank_limit", "score_sources", "ranking", "rank_rewards", "redemption"}
    if set(row) != required:
        raise ContentError("domain war season has missing or unknown fields")
    name = _required_text(row["name"], "season name")
    desc = _required_text(row["desc"], "season desc")
    anchor = _utc_midnight(row["anchor"], "domain war season anchor")
    duration = _positive(row["duration_days"], "season duration_days")
    claim_days = _positive(row["claim_days"], "season claim_days")
    rank_limit = _positive(row["rank_limit"], "season rank_limit")
    sources = row["score_sources"]
    if not isinstance(sources, dict) or set(sources) != {"domain_contribution", "sect_contribution", "soul_transformation_production"}:
        raise ContentError("domain war score_sources are invalid")
    source_fields = {
        "domain_contribution": {"multiplier"},
        "sect_contribution": {"multiplier"},
        "soul_transformation_production": {"multiplier", "recipe_key_prefix", "snapshot_realm_key"},
    }
    multipliers: list[int] = []
    for key, expected_source_fields in source_fields.items():
        source = sources[key]
        if not isinstance(source, dict) or set(source) != expected_source_fields:
            raise ContentError(f"domain war source {key} is invalid")
        multipliers.append(_positive(source["multiplier"], f"season {key} multiplier"))
    production_source = sources["soul_transformation_production"]
    production_recipe_key_prefix = _required_text(production_source["recipe_key_prefix"], "production recipe key prefix")
    production_snapshot_realm_key = _required_text(production_source["snapshot_realm_key"], "production snapshot realm key")
    if not bundle.has("realm", production_snapshot_realm_key, include_locked=False):
        raise ContentError(f"domain war production realm is inactive: {production_snapshot_realm_key}")
    ranking = row["ranking"]
    if not isinstance(ranking, dict) or set(ranking) != {"score_order", "achieved_at_order", "identity_tiebreak"}:
        raise ContentError("domain war ranking is invalid")
    score_order = _required_text(ranking["score_order"], "score order")
    achieved_at_order = _required_text(ranking["achieved_at_order"], "achieved-at order")
    identity_tiebreak = _required_text(ranking["identity_tiebreak"], "identity tiebreak")
    if score_order not in {"asc", "desc"} or achieved_at_order not in {"asc", "desc"} or identity_tiebreak not in {"player_id_asc", "player_id_desc"}:
        raise ContentError("domain war ranking directions are invalid")
    raw_rewards = row["rank_rewards"]
    if not isinstance(raw_rewards, list) or not raw_rewards:
        raise ContentError("domain war rank_rewards must be non-empty")
    rank_rewards: list[tuple[int, int, str, RewardGrant, str, str, tuple[tuple[str, int], ...]]] = []
    expected = 1
    for item in raw_rewards:
        if not isinstance(item, dict) or set(item) != {"min_rank", "max_rank", "reward_key"}:
            raise ContentError("domain war rank reward is invalid")
        minimum = _positive(item["min_rank"], "rank reward min_rank")
        maximum = _positive(item["max_rank"], "rank reward max_rank")
        if minimum != expected or maximum < minimum or maximum > rank_limit:
            raise ContentError("domain war rank reward ranges must be contiguous")
        reward_key = _required_text(item["reward_key"], "rank reward key")
        reward = reward_definition(reward_key, bundle, operation="event.domain_war.claim")
        reward_caps = _reward_caps(reward, bundle)
        reward_row = bundle.require("reward", reward_key, include_locked=False)
        rank_rewards.append((minimum, maximum, reward_key, reward, _required_text(reward_row.get("name"), "rank reward name"), _required_text(reward_row.get("desc"), "rank reward desc"), reward_caps))
        expected = maximum + 1
    if expected != rank_limit + 1:
        raise ContentError("domain war rank rewards must cover the rank limit")
    redemption = row["redemption"]
    if not isinstance(redemption, dict) or set(redemption) != {"fragment_item_key", "fragment_quantity", "reward_item_key", "reward_quantity"}:
        raise ContentError("domain war redemption is invalid")
    fragment_item = _required_text(redemption["fragment_item_key"], "fragment item key")
    reward_item = _required_text(redemption["reward_item_key"], "reward item key")
    if not bundle.has("item", fragment_item, include_locked=False) or not bundle.has("item", reward_item, include_locked=False):
        raise ContentError("domain war redemption references inactive item")
    return DomainWarSeasonDefinition(
        season_key=SEASON_KEY,
        name=name,
        desc=desc,
        anchor=anchor,
        duration_days=duration,
        claim_days=claim_days,
        rank_limit=rank_limit,
        domain_multiplier=multipliers[0],
        sect_multiplier=multipliers[1],
        production_multiplier=multipliers[2],
        production_recipe_key_prefix=production_recipe_key_prefix,
        production_snapshot_realm_key=production_snapshot_realm_key,
        score_order=score_order,
        achieved_at_order=achieved_at_order,
        identity_tiebreak=identity_tiebreak,
        rank_rewards=tuple(rank_rewards),
        fragment_item_key=fragment_item,
        fragment_quantity=_positive(redemption["fragment_quantity"], "fragment quantity"),
        reward_item_key=reward_item,
        reward_quantity=_positive(redemption["reward_quantity"], "reward quantity"),
    )


def domain_front_definition_from_snapshot(value: Any) -> DomainFrontDefinition:
    if not isinstance(value, dict):
        raise ContentError("domain front snapshot must be an object")
    expected = {"event_key", "name", "desc", "location_key", "required_realm_key", "required_realm_layer", "required_realm_rank", "activity_hours", "anchor_hour", "round_minutes", "claim_days", "participant_cap", "join_stamina_cost", "sect_level_min", "battle_contribution", "point_contribution_per_minute", "point_minutes_min", "point_minutes_max", "target_quantity", "personal_claim_threshold", "reward_key", "reward", "reward_name", "reward_desc", "reward_local_reputation_maximums", "codex_entry_key"}
    if set(value) != expected:
        raise ContentError("domain front snapshot has missing or unknown fields")
    text_fields = ("event_key", "name", "desc", "location_key", "required_realm_key", "reward_key", "reward_name", "reward_desc", "codex_entry_key")
    for field in text_fields:
        _required_text(value.get(field), f"snapshot {field}")
    ints = ("required_realm_layer", "required_realm_rank", "activity_hours", "round_minutes", "claim_days", "participant_cap", "join_stamina_cost", "sect_level_min", "battle_contribution", "point_contribution_per_minute", "point_minutes_min", "point_minutes_max", "target_quantity", "personal_claim_threshold")
    normalized = {field: _positive(value.get(field), f"snapshot {field}") for field in ints}
    anchor_hour = value["anchor_hour"]
    if isinstance(anchor_hour, bool) or not isinstance(anchor_hour, int) or not 0 <= anchor_hour <= 23:
        raise ContentError("domain front snapshot anchor_hour is invalid")
    if normalized["activity_hours"] * 60 % normalized["round_minutes"] != 0 or normalized["point_minutes_min"] > normalized["point_minutes_max"]:
        raise ContentError("domain front snapshot has invalid bounds")
    reward = reward_grant_from_snapshot(value["reward"], operation="event.domain_front.claim")
    reward_caps = _snapshot_reward_caps(value["reward_local_reputation_maximums"], reward, "domain front snapshot reward caps")
    if value["event_key"] != EVENT_KEY:
        raise ContentError("domain front snapshot event key is invalid")
    return DomainFrontDefinition(
        event_key=EVENT_KEY,
        name=str(value["name"]),
        desc=str(value["desc"]),
        status="active",
        location_key=str(value["location_key"]),
        required_realm_key=str(value["required_realm_key"]),
        required_realm_layer=normalized["required_realm_layer"],
        required_realm_rank=normalized["required_realm_rank"],
        activity_hours=normalized["activity_hours"],
        anchor_hour=anchor_hour,
        round_minutes=normalized["round_minutes"],
        claim_days=normalized["claim_days"],
        participant_cap=normalized["participant_cap"],
        join_stamina_cost=normalized["join_stamina_cost"],
        sect_level_min=normalized["sect_level_min"],
        battle_contribution=normalized["battle_contribution"],
        point_contribution_per_minute=normalized["point_contribution_per_minute"],
        point_minutes_min=normalized["point_minutes_min"],
        point_minutes_max=normalized["point_minutes_max"],
        target_quantity=normalized["target_quantity"],
        personal_claim_threshold=normalized["personal_claim_threshold"],
        reward_key=str(value["reward_key"]),
        reward=reward,
        reward_name=str(value["reward_name"]),
        reward_desc=str(value["reward_desc"]),
        reward_local_reputation_maximums=reward_caps,
        codex_entry_key=str(value["codex_entry_key"]),
    )


def domain_war_season_definition_from_snapshot(value: Any) -> DomainWarSeasonDefinition:
    if not isinstance(value, dict):
        raise ContentError("domain war season snapshot must be an object")
    expected = {"season_key", "name", "desc", "anchor", "duration_days", "claim_days", "rank_limit", "score_sources", "ranking", "rank_rewards", "redemption"}
    if set(value) != expected:
        raise ContentError("domain war season snapshot has missing or unknown fields")
    anchor = _utc_midnight(value["anchor"], "domain war season snapshot anchor")
    sources = value["score_sources"]
    if not isinstance(sources, dict) or set(sources) != {"domain_contribution", "sect_contribution", "soul_transformation_production"}:
        raise ContentError("domain war season snapshot sources are invalid")
    source_fields = {
        "domain_contribution": {"multiplier"},
        "sect_contribution": {"multiplier"},
        "soul_transformation_production": {"multiplier", "recipe_key_prefix", "snapshot_realm_key"},
    }
    source_values: list[int] = []
    for key, expected_source_fields in source_fields.items():
        source = sources[key]
        if not isinstance(source, dict) or set(source) != expected_source_fields:
            raise ContentError("domain war season snapshot source is invalid")
        source_values.append(_positive(source["multiplier"], f"snapshot {key} multiplier"))
    production_source = sources["soul_transformation_production"]
    production_recipe_key_prefix = _required_text(production_source["recipe_key_prefix"], "snapshot production recipe key prefix")
    production_snapshot_realm_key = _required_text(production_source["snapshot_realm_key"], "snapshot production realm")
    ranking = value["ranking"]
    if not isinstance(ranking, dict) or set(ranking) != {"score_order", "achieved_at_order", "identity_tiebreak"}:
        raise ContentError("domain war season snapshot ranking is invalid")
    score_order = _required_text(ranking["score_order"], "snapshot score order")
    achieved_at_order = _required_text(ranking["achieved_at_order"], "snapshot achieved-at order")
    identity_tiebreak = _required_text(ranking["identity_tiebreak"], "snapshot identity tiebreak")
    if score_order not in {"asc", "desc"} or achieved_at_order not in {"asc", "desc"} or identity_tiebreak not in {"player_id_asc", "player_id_desc"}:
        raise ContentError("domain war season snapshot ranking directions are invalid")
    raw_rewards = value["rank_rewards"]
    if not isinstance(raw_rewards, list) or not raw_rewards:
        raise ContentError("domain war season snapshot rewards are invalid")
    rank_rewards: list[tuple[int, int, str, RewardGrant, str, str, tuple[tuple[str, int], ...]]] = []
    expected_rank = 1
    rank_limit = _positive(value["rank_limit"], "snapshot rank_limit")
    for item in raw_rewards:
        if not isinstance(item, dict) or set(item) != {"min_rank", "max_rank", "reward_key", "reward", "reward_name", "reward_desc", "local_reputation_maximums"}:
            raise ContentError("domain war season snapshot rank reward is invalid")
        minimum = _positive(item["min_rank"], "snapshot min_rank")
        maximum = _positive(item["max_rank"], "snapshot max_rank")
        if minimum != expected_rank or maximum < minimum or maximum > rank_limit:
            raise ContentError("domain war season snapshot rank ranges are invalid")
        reward = reward_grant_from_snapshot(item["reward"], operation="event.domain_war.claim")
        reward_caps = _snapshot_reward_caps(item["local_reputation_maximums"], reward, "season snapshot reward caps")
        rank_rewards.append((minimum, maximum, _required_text(item["reward_key"], "snapshot reward key"), reward, _required_text(item["reward_name"], "snapshot rank reward name"), _required_text(item["reward_desc"], "snapshot rank reward desc"), reward_caps))
        expected_rank = maximum + 1
    if expected_rank != rank_limit + 1:
        raise ContentError("domain war season snapshot rank ranges are incomplete")
    redemption = value["redemption"]
    if not isinstance(redemption, dict) or set(redemption) != {"fragment_item_key", "fragment_quantity", "reward_item_key", "reward_quantity"}:
        raise ContentError("domain war season snapshot redemption is invalid")
    if value["season_key"] != SEASON_KEY:
        raise ContentError("domain war season snapshot key is invalid")
    return DomainWarSeasonDefinition(
        season_key=SEASON_KEY,
        name=_required_text(value["name"], "snapshot name"),
        desc=_required_text(value["desc"], "snapshot desc"),
        anchor=anchor,
        duration_days=_positive(value["duration_days"], "snapshot duration_days"),
        claim_days=_positive(value["claim_days"], "snapshot claim_days"),
        rank_limit=rank_limit,
        domain_multiplier=source_values[0],
        sect_multiplier=source_values[1],
        production_multiplier=source_values[2],
        production_recipe_key_prefix=production_recipe_key_prefix,
        production_snapshot_realm_key=production_snapshot_realm_key,
        score_order=score_order,
        achieved_at_order=achieved_at_order,
        identity_tiebreak=identity_tiebreak,
        rank_rewards=tuple(rank_rewards),
        fragment_item_key=_required_text(redemption["fragment_item_key"], "snapshot fragment key"),
        fragment_quantity=_positive(redemption["fragment_quantity"], "snapshot fragment quantity"),
        reward_item_key=_required_text(redemption["reward_item_key"], "snapshot reward key"),
        reward_quantity=_positive(redemption["reward_quantity"], "snapshot reward quantity"),
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def domain_rank(realm_key: str, content: ContentBundle | None = None) -> int:
    row = (content or bundled_content()).get("realm", realm_key)
    return int(row["rank"]) if row is not None and isinstance(row.get("rank"), int) else -1


def meets_domain_front_realm(realm_key: str, layer: int, required_realm_rank: int, required_layer: int, content: ContentBundle | None = None) -> bool:
    return (domain_rank(realm_key, content), int(layer)) >= (int(required_realm_rank), int(required_layer))


def activity_window(now: datetime, definition: DomainFrontDefinition | None = None) -> tuple[str, datetime, datetime]:
    definition = definition or domain_front_definition()
    value = _utc(now)
    anchor = value.replace(hour=definition.anchor_hour, minute=0, second=0, microsecond=0)
    if value < anchor:
        anchor -= timedelta(days=1)
    block_seconds = definition.activity_hours * 60 * 60
    elapsed_seconds = int((value - anchor).total_seconds())
    block_index = elapsed_seconds // block_seconds
    starts_at = anchor + timedelta(seconds=block_index * block_seconds)
    ends_at = starts_at + timedelta(hours=definition.activity_hours)
    return f"{EVENT_KEY}:{starts_at:%Y%m%d%H}", starts_at, ends_at


def round_window(now: datetime, definition: DomainFrontDefinition | None = None) -> tuple[str, str, datetime, datetime, datetime, datetime]:
    definition = definition or domain_front_definition()
    activity_id, activity_start, activity_end = activity_window(now, definition)
    value = _utc(now)
    elapsed_minutes = max(0, int((value - activity_start).total_seconds() // 60))
    round_index = min(elapsed_minutes // definition.round_minutes, (definition.activity_hours * 60 // definition.round_minutes) - 1)
    starts_at = activity_start + timedelta(minutes=round_index * definition.round_minutes)
    ends_at = min(starts_at + timedelta(minutes=definition.round_minutes), activity_end)
    round_id = f"{activity_id}:r{round_index + 1}"
    return round_id, activity_id, activity_start, activity_end, starts_at, ends_at


def season_window(now: datetime, definition: DomainWarSeasonDefinition | None = None) -> tuple[str, datetime, datetime]:
    definition = definition or domain_war_season_definition()
    value = _utc(now)
    season_seconds = definition.duration_days * 24 * 60 * 60
    offset = int((value - definition.anchor).total_seconds() // season_seconds)
    starts_at = definition.anchor + timedelta(days=offset * definition.duration_days)
    ends_at = starts_at + timedelta(days=definition.duration_days)
    return f"{SEASON_KEY}:{starts_at:%Y%m%d}", starts_at, ends_at


def season_window_for_id(season_id: str, definition: DomainWarSeasonDefinition | None = None) -> tuple[str, datetime, datetime]:
    prefix = f"{SEASON_KEY}:"
    if not season_id.startswith(prefix):
        raise ValueError("invalid domain-war season id")
    try:
        starts_at = datetime.strptime(season_id[len(prefix) :], "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("invalid domain-war season id") from exc
    canonical_id, canonical_start, ends_at = season_window(starts_at, definition)
    if canonical_id != season_id or canonical_start != starts_at:
        raise ValueError("invalid domain-war season window")
    return canonical_id, starts_at, ends_at


def claim_expiry(ends_at: datetime, definition: DomainWarSeasonDefinition | None = None) -> datetime:
    return ends_at + timedelta(days=(definition or domain_war_season_definition()).claim_days)


def anonymous_label(season_id: str, player_id: int) -> str:
    digest = hashlib.sha256(f"{season_id}:{player_id}".encode("ascii")).hexdigest()[:8]
    return f"领域道友-{digest}"


__all__ = [
    "ACTION_VALUES",
    "DomainFrontDefinition",
    "DomainWarSeasonDefinition",
    "EVENT_KEY",
    "LOCATION_KEY",
    "SEASON_KEY",
    "activity_window",
    "anonymous_label",
    "claim_expiry",
    "domain_rank",
    "meets_domain_front_realm",
    "domain_front_definition",
    "domain_front_definition_from_snapshot",
    "domain_war_season_definition",
    "domain_war_season_definition_from_snapshot",
    "round_window",
    "season_window",
    "season_window_for_id",
]
