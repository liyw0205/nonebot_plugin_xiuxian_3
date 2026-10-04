"""Pure routine rules."""

from __future__ import annotations


from datetime import date, timedelta
import hashlib
import json
from dataclasses import dataclass
from typing import Any


CHECKIN_ACTIVITY = "ritual.checkin.daily"
MAKEUP_ACTIVITY = "ritual.makeup.daily"
TREE_WATER_ACTIVITY = "ritual.spirit_tree.water"
TREE_HARVEST_ACTIVITY = "ritual.spirit_tree.harvest"
TREE_HARVEST_REWARD_POOL = "reward_pool.routine.spirit_tree_harvest"
FATE_TICKET = "item.ticket.fate_basic"


@dataclass(frozen=True, slots=True)
class SevenDayGoalDefinition:
    day_number: int
    key: str
    label: str
    reward: tuple[tuple[str, int], ...]
    event_key: str
    closed: bool = False
    local_reputation_key: str | None = None


SEVEN_DAY_GOALS: tuple[SevenDayGoalDefinition, ...] = (
    SevenDayGoalDefinition(
        1,
        "quest.seven_day.day1_checkin",
        "道历问安",
        (("item.food.coarse_spirit_rice", 1),),
        "routine.checkin.daily",
    ),
    SevenDayGoalDefinition(
        2,
        "quest.seven_day.day2_gather",
        "完成一次近郊采集",
        (("item.herb.blood_grass", 2),),
        "explore.gather_outskirts",
    ),
    SevenDayGoalDefinition(
        3,
        "quest.seven_day.day3_production_preview",
        "查看一次生产预览或开始生产",
        (("spirit_stones", 30),),
        "production.preview",
    ),
    SevenDayGoalDefinition(
        4,
        "quest.seven_day.day4_bounty",
        "接取一次悬赏",
        (("local_reputation", 2),),
        "bounty.accept",
        local_reputation_key="local.xuantian.new_town",
    ),
    SevenDayGoalDefinition(
        5,
        "quest.seven_day.day5_tower",
        "完成试炼塔一层",
        (("item.mat.array_sand", 2),),
        "specials.tower.floor.1",
    ),
    SevenDayGoalDefinition(
        6,
        "quest.seven_day.day6_dispatch",
        "完成一次派遣",
        (("spirit_stones", 50),),
        "specials.dispatch.settled",
    ),
    SevenDayGoalDefinition(
        7,
        "quest.seven_day.day7_path",
        "选择道途",
        (("local_reputation", 5), (FATE_TICKET, 2)),
        "player.enter_cultivation",
        local_reputation_key="local.xuantian.new_town",
    ),
)


@dataclass(frozen=True, slots=True)
class HonorTitleDefinition:
    key: str
    label: str
    source_event: str
    closed: bool = False


@dataclass(frozen=True, slots=True)
class AchievementDefinition:
    key: str
    label: str
    source_event: str
    reward: tuple[tuple[str, int | str], ...]
    closed: bool = False


@dataclass(frozen=True, slots=True)
class RedemptionCodeDefinition:
    """A validated externally configured code; plaintext is never retained."""

    code_key: str
    code_hash: str
    reward: tuple[tuple[str, int], ...]
    max_claims: int = 1000
    starts_on: str | None = None
    ends_on: str | None = None
    revoked: bool = False

    def reward_map(self) -> dict[str, int]:
        return {key: int(value) for key, value in self.reward}

    def available_on(self, business_date: date) -> bool:
        if self.revoked:
            return False
        if self.starts_on and business_date < date.fromisoformat(self.starts_on):
            return False
        if self.ends_on and business_date > date.fromisoformat(self.ends_on):
            return False
        return True


@dataclass(frozen=True, slots=True)
class DaoContractDefinition:
    key: str
    label: str
    duration_days: int
    price: int
    daily_reward: tuple[tuple[str, int], ...]
    activation_reward: tuple[tuple[str, int], ...] = ()
    reputation_every_days: int | None = None
    reputation_reward: int = 0

    def daily_reward_map(self) -> dict[str, int]:
        return {key: int(value) for key, value in self.daily_reward}

    def activation_reward_map(self) -> dict[str, int]:
        return {key: int(value) for key, value in self.activation_reward}


HONOR_TITLES: tuple[HonorTitleDefinition, ...] = (
    HonorTitleDefinition("title.first_seeking", "初入道途", "player.start_seeking"),
    HonorTitleDefinition("title.town_helper", "城镇助行者", "routine.checkin.daily:3"),
    HonorTitleDefinition(
        "title.mist_watcher",
        "雾中守门人",
        "story.mainline.xuantian:chapter.1.stage.3",
    ),
    HonorTitleDefinition("title.dispatch_helper", "派遣行者", "specials.dispatch.settled"),
    HonorTitleDefinition("title.first_tower_clear", "试炼先行", "specials.tower.floor.10"),
    HonorTitleDefinition(
        "title.three_realms_tower.domain_guardian",
        "三界守界人",
        "specials.three_realms_tower.floor.40",
    ),
    HonorTitleDefinition(
        "title.season.final_heaven.ascension",
        "凌霄先登",
        "season.final_heaven.claim.ascension",
    ),
    HonorTitleDefinition(
        "title.season.final_heaven.dao",
        "留界道统",
        "season.final_heaven.claim.dao",
    ),
    HonorTitleDefinition(
        "title.season.final_heaven.cooperation",
        "同道共济",
        "season.final_heaven.claim.cooperation",
    ),
    HonorTitleDefinition(
        "title.void_spire.witness",
        "虚空见证者",
        "specials.void_spire.floor.60",
    ),
    HonorTitleDefinition(
        "title.void_spire.origin",
        "道源登塔者",
        "specials.void_spire.floor.75",
    ),
    HonorTitleDefinition(
        "title.void_spire.ascension",
        "虚空登临者",
        "specials.void_spire.floor.90",
    ),
)


DAO_CONTRACTS: tuple[DaoContractDefinition, ...] = (
    DaoContractDefinition(
        "dao_contract.daily",
        "日道契",
        duration_days=1,
        price=30,
        daily_reward=(("spirit_stones", 30), ("energy", 2)),
    ),
    DaoContractDefinition(
        "dao_contract.weekly",
        "周道契",
        duration_days=7,
        price=180,
        daily_reward=(("spirit_stones", 35), ("energy", 3)),
        activation_reward=((FATE_TICKET, 2),),
    ),
    DaoContractDefinition(
        "dao_contract.monthly",
        "月道契",
        duration_days=30,
        price=600,
        daily_reward=(("spirit_stones", 40), ("energy", 4)),
        activation_reward=(("item.cosmetic.dao_name_frame", 1),),
        reputation_every_days=7,
        reputation_reward=3,
    ),
)


ACHIEVEMENTS: tuple[AchievementDefinition, ...] = (
    AchievementDefinition(
        "achievement.first_checkin",
        "首次道历问安",
        "routine.checkin.daily",
        (("local_reputation", 3),),
    ),
    AchievementDefinition(
        "achievement.first_craft",
        "首次完成生产",
        "production.complete",
        (("service_reputation", 2),),
    ),
    AchievementDefinition(
        "achievement.first_dispatch",
        "首次完成派遣",
        "specials.dispatch.settled",
        (("title_key", "title.dispatch_helper"),),
    ),
    AchievementDefinition(
        "achievement.codex_5",
        "收录五条图鉴",
        "specials.codex.count.5",
        (("local_reputation", 5),),
    ),
    AchievementDefinition(
        "achievement.tower_10",
        "试炼塔十层",
        "specials.tower.floor.10",
        (("title_key", "title.first_tower_clear"),),
    ),
)


_REDEMPTION_FORBIDDEN_KEYS = frozenset(
    {
        "cultivation",
        "total_cultivation",
        "realm_layer",
        "foundation_quality",
        "world_merit",
        "breakthrough_pity_bp",
        "dao_contract",
        "fate_pool",
    }
)


def normalize_redemption_code(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("redemption code must be a string")
    normalized = value.strip().casefold()
    if not normalized or len(normalized) > 256:
        raise ValueError("redemption code must be 1-256 characters")
    return normalized


def redemption_code_hash(value: str) -> str:
    normalized = normalize_redemption_code(value)
    return hashlib.sha256(
        f"redemption.code:{normalized}".encode("utf-8")
    ).hexdigest()


def redemption_code_definition(
    code_key: str,
    plaintext: str,
    reward: dict[str, int] | tuple[tuple[str, int], ...],
    *,
    max_claims: int = 1000,
    starts_on: str | None = None,
    ends_on: str | None = None,
    revoked: bool = False,
) -> RedemptionCodeDefinition:
    if not isinstance(code_key, str) or not code_key.startswith("code."):
        raise ValueError("redemption code key must start with code.")
    if not isinstance(max_claims, int) or max_claims < 1:
        raise ValueError("redemption code max_claims must be positive")
    for boundary in (starts_on, ends_on):
        if boundary is not None:
            try:
                date.fromisoformat(boundary)
            except (TypeError, ValueError) as exc:
                raise ValueError("redemption code dates must be ISO dates") from exc
    if starts_on and ends_on and starts_on > ends_on:
        raise ValueError("redemption code starts_on must not exceed ends_on")
    items = reward.items() if isinstance(reward, dict) else reward
    normalized_reward: list[tuple[str, int]] = []
    for key, quantity in items:
        if not isinstance(key, str) or not key:
            raise ValueError("redemption reward key is required")
        if key in _REDEMPTION_FORBIDDEN_KEYS or key.startswith("realm."):
            raise ValueError(f"redemption reward is forbidden: {key}")
        if key not in {"spirit_stones", "energy", "local_reputation", "service_reputation"} and not key.startswith("item."):
            raise ValueError(f"unsupported redemption reward: {key}")
        if not isinstance(quantity, int) or quantity < 1:
            raise ValueError("redemption reward quantities must be positive integers")
        normalized_reward.append((key, quantity))
    if not normalized_reward:
        raise ValueError("redemption reward cannot be empty")
    return RedemptionCodeDefinition(
        code_key=code_key,
        code_hash=redemption_code_hash(plaintext),
        reward=tuple(normalized_reward),
        max_claims=max_claims,
        starts_on=starts_on,
        ends_on=ends_on,
        revoked=bool(revoked),
    )


def redemption_codes_from_config(value: Any) -> tuple[RedemptionCodeDefinition, ...]:
    if value in (None, "", []):
        return ()
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("XIUXIAN3_REDEMPTION_CODES must be valid JSON") from exc
    if not isinstance(value, list):
        raise ValueError("redemption code configuration must be a JSON list")
    definitions: list[RedemptionCodeDefinition] = []
    keys: set[str] = set()
    hashes: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each redemption code must be an object")
        if "code_key" not in item or "code" not in item or "reward" not in item:
            raise ValueError("redemption code requires code_key, code and reward")
        definition = redemption_code_definition(
            str(item["code_key"]),
            str(item["code"]),
            item["reward"],
            max_claims=item.get("max_claims", 1000),
            starts_on=item.get("starts_on"),
            ends_on=item.get("ends_on"),
            revoked=item.get("revoked", False),
        )
        if definition.code_key in keys or definition.code_hash in hashes:
            raise ValueError("redemption code keys and values must be unique")
        keys.add(definition.code_key)
        hashes.add(definition.code_hash)
        definitions.append(definition)
    return tuple(definitions)


def seven_day_goal(day_number: int) -> SevenDayGoalDefinition:
    if day_number < 1 or day_number > len(SEVEN_DAY_GOALS):
        raise ValueError("invalid seven-day goal")
    return SEVEN_DAY_GOALS[day_number - 1]


def seven_day_reward(goal: SevenDayGoalDefinition) -> dict[str, int]:
    return {key: int(value) for key, value in goal.reward}


def honor_title(key: str) -> HonorTitleDefinition:
    for definition in HONOR_TITLES:
        if definition.key == key:
            return definition
    raise ValueError(f"unsupported honor title: {key}")


def dao_contract(key: str) -> DaoContractDefinition:
    for definition in DAO_CONTRACTS:
        if definition.key == key:
            return definition
    raise ValueError(f"unsupported dao contract: {key}")


def achievement(key: str) -> AchievementDefinition:
    for definition in ACHIEVEMENTS:
        if definition.key == key:
            return definition
    raise ValueError(f"unsupported achievement: {key}")


def achievement_reward(definition: AchievementDefinition) -> dict[str, int | str]:
    return {
        key: (int(value) if isinstance(value, int) else str(value))
        for key, value in definition.reward
    }


def parse_past_date(value: str, today: date) -> date:
    """Parse an ISO date and require a target in the previous three days."""

    try:
        target = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid business date") from exc
    age = (today - target).days
    if age < 1 or age > 3:
        raise ValueError("date is outside the makeup window")
    if target.month != today.month or target.year != today.year:
        raise ValueError("date is outside the current business month")
    return target


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid business date") from exc


def checkin_reward(streak: int) -> dict[str, int]:
    reward = {"spirit_stones": 20, "energy": 3}
    if streak > 0 and streak % 7 == 0:
        reward[FATE_TICKET] = 1
    return reward


def makeup_reward() -> dict[str, int]:
    # The documented 80% reward is rounded down for integer assets.
    return {"spirit_stones": 16, "energy": 2}


def tree_status(water_count: int, cooldown_until: str | None, now_iso: str) -> str:
    if cooldown_until and now_iso < cooldown_until:
        return "cooldown"
    if water_count >= 7:
        return "ready"
    if water_count:
        return "watered"
    return "dormant"


def next_date(value: date) -> date:
    return value + timedelta(days=1)


__all__ = [
    "CHECKIN_ACTIVITY",
    "FATE_TICKET",
    "MAKEUP_ACTIVITY",
    "TREE_HARVEST_ACTIVITY",
    "TREE_HARVEST_REWARD_POOL",
    "TREE_WATER_ACTIVITY",
    "SEVEN_DAY_GOALS",
    "HONOR_TITLES",
    "ACHIEVEMENTS",
    "HonorTitleDefinition",
    "AchievementDefinition",
    "RedemptionCodeDefinition",
    "DaoContractDefinition",
    "SevenDayGoalDefinition",
    "checkin_reward",
    "makeup_reward",
    "next_date",
    "parse_iso_date",
    "parse_past_date",
    "tree_status",
    "seven_day_goal",
    "seven_day_reward",
    "honor_title",
    "achievement",
    "achievement_reward",
    "normalize_redemption_code",
    "redemption_code_hash",
    "redemption_code_definition",
    "redemption_codes_from_config",
    "DAO_CONTRACTS",
    "dao_contract",
]
