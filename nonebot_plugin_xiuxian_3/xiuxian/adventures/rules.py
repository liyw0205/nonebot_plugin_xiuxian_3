"""Pure, versioned v0.1 bounty rules."""

from __future__ import annotations

from dataclasses import dataclass


RULE_VERSION = "adventures-0.1.0"
CONTENT_VERSION = "content-0.1"


@dataclass(frozen=True, slots=True)
class BountyDefinition:
    key: str
    label: str
    description: str
    required_realm: str | None
    required_layer: int
    duration_seconds: int
    daily_limit: int
    target_kind: str
    target_key: str | None
    target_amount: int
    reward: tuple[tuple[str, int], ...]
    reputation_key: str = "local.xuantian.new_town"
    runtime_status: str = "open"
    rule_version: str = RULE_VERSION
    content_version: str = CONTENT_VERSION


DEFINITIONS: dict[str, BountyDefinition] = {
    "bounty.herb_supply": BountyDefinition(
        key="bounty.herb_supply",
        label="草药补给",
        description="获得止血草 5 株",
        required_realm="mortal",
        required_layer=0,
        duration_seconds=30 * 60,
        daily_limit=1,
        target_kind="inventory_gain",
        target_key="item.herb.blood_grass",
        target_amount=5,
        reward=(("spirit_stones", 30), ("local_reputation", 2)),
    ),
    "bounty.training_dummy": BountyDefinition(
        key="bounty.training_dummy",
        label="训练傀儡",
        description="战胜训练傀儡 2 次",
        required_realm="qi_sensing",
        required_layer=1,
        duration_seconds=60 * 60,
        daily_limit=1,
        target_kind="training_dummy_wins",
        target_key="enemy.training_dummy",
        target_amount=2,
        reward=(("cultivation", 120), ("item.pill.focus_low", 1)),
        runtime_status="locked",
    ),
    "bounty.craft_order": BountyDefinition(
        key="bounty.craft_order",
        label="生产订单",
        description="完成任意生产订单 1 次",
        required_realm=None,
        required_layer=0,
        duration_seconds=2 * 60 * 60,
        daily_limit=1,
        target_kind="production_completed",
        target_key=None,
        target_amount=1,
        reward=(("energy", 10), ("service_reputation", 2)),
    ),
    "bounty.cloud_mine": BountyDefinition(
        key="bounty.cloud_mine",
        label="云铁矿区悬赏",
        description="交付云铁 3 块",
        required_realm="foundation",
        required_layer=4,
        duration_seconds=2 * 60 * 60,
        daily_limit=1,
        target_kind="inventory_gain",
        target_key="item.material.cloud_iron",
        target_amount=3,
        reward=(("spirit_stones", 120), ("local_reputation", 8)),
        reputation_key="local.xuantian.cloud_city",
        rule_version="adventures-0.2.0",
        content_version="content-0.2",
    ),
    "bounty.elite_hunt": BountyDefinition(
        key="bounty.elite_hunt",
        label="洞天精英悬赏",
        description="在洞天二层击败雾隐精英 1 次",
        required_realm="golden_core",
        required_layer=1,
        duration_seconds=4 * 60 * 60,
        daily_limit=1,
        target_kind="exploration_battle_wins",
        target_key="enemy.mist_elite",
        target_amount=1,
        reward=(("item.cave_pass_advanced", 1), ("local_reputation", 12)),
        reputation_key="local.xuantian.cloud_city",
        rule_version="adventures-0.2.0",
        content_version="content-0.2",
    ),
}


ALIASES = {
    **{key: key for key in DEFINITIONS},
    "草药补给": "bounty.herb_supply",
    "止血草补给": "bounty.herb_supply",
    "训练傀儡": "bounty.training_dummy",
    "生产订单": "bounty.craft_order",
    "生产": "bounty.craft_order",
    "云铁矿区悬赏": "bounty.cloud_mine",
    "云铁悬赏": "bounty.cloud_mine",
    "洞天精英悬赏": "bounty.elite_hunt",
    "精英悬赏": "bounty.elite_hunt",
}


def resolve_bounty(value: str) -> str | None:
    return ALIASES.get(value.strip())


def bounty_definition(key: str) -> BountyDefinition:
    try:
        return DEFINITIONS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported bounty: {key}") from exc


def realm_rank(realm_key: str) -> int:
    return {
        "mortal": 0,
        "qi_sensing": 1,
        "qi_gathering": 2,
        "foundation": 3,
        "golden_core": 4,
        "nascent_soul": 5,
        "soul_transformation": 6,
    }.get(realm_key, -1)


def meets_realm(realm_key: str, layer: int, required_realm: str | None, required_layer: int) -> bool:
    if required_realm is None:
        return True
    return (realm_rank(realm_key), int(layer)) >= (realm_rank(required_realm), required_layer)


def reward_map(definition: BountyDefinition) -> dict[str, int]:
    return {key: int(value) for key, value in definition.reward}


__all__ = [
    "ALIASES",
    "CONTENT_VERSION",
    "DEFINITIONS",
    "RULE_VERSION",
    "BountyDefinition",
    "bounty_definition",
    "meets_realm",
    "realm_rank",
    "resolve_bounty",
    "reward_map",
]
