"""Pure rules for residence and the first livelihood crop slice."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


TOWN_ROOM = "residence.town_room"
COURTYARD = "residence.courtyard"
CONTENT_VERSION = "content-0.1"
RULE_VERSION = "livelihood-0.1.0"


@dataclass(frozen=True, slots=True)
class ResidenceDefinition:
    key: str
    label: str
    rent_cost: int
    lease_days: int
    required_stage: str
    required_local_reputation: int = 0
    plot_count: int = 0
    content_version: str = CONTENT_VERSION
    rule_version: str = RULE_VERSION


RESIDENCE_DEFINITIONS = {
    TOWN_ROOM: ResidenceDefinition(
        key=TOWN_ROOM,
        label="青石镇客房",
        rent_cost=20,
        lease_days=3,
        required_stage="mortal",
        plot_count=1,
    ),
    COURTYARD: ResidenceDefinition(
        key=COURTYARD,
        label="小院",
        rent_cost=80,
        lease_days=7,
        required_stage="mortal",
        required_local_reputation=40,
        plot_count=1,
    ),
}

RESIDENCE_ALIASES = {
    "客房": TOWN_ROOM,
    "青石镇客房": TOWN_ROOM,
    "小屋": TOWN_ROOM,
    "小院": COURTYARD,
}


def residence_definition(value: str | None = None) -> ResidenceDefinition:
    key = RESIDENCE_ALIASES.get((value or "客房").strip(), value or TOWN_ROOM)
    try:
        return RESIDENCE_DEFINITIONS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported residence key: {value}") from exc


BLOOD_GRASS = "crop.blood_grass"
SPIRIT_LEAF = "crop.spirit_leaf"
SPIRIT_LEAF_HARVEST_POOL = "livelihood.harvest.v0.1"


@dataclass(frozen=True, slots=True)
class CropDefinition:
    key: str
    label: str
    seed_key: str
    growth_seconds: int
    maintenance_energy: int
    required_maintenance: int
    maintained_harvest: dict[str, int]
    unmaintained_harvest: dict[str, int]
    daily_limit: int
    residence_key: str | None = None
    random_pool: str | None = None
    content_version: str = CONTENT_VERSION
    rule_version: str = RULE_VERSION


@dataclass(frozen=True, slots=True)
class TownCommissionDefinition:
    key: str
    label: str
    inputs: dict[str, int]
    reward_stones: int
    local_reputation: int
    service_reputation: int
    stock: int
    duration_seconds: int = 12 * 60 * 60
    content_version: str = CONTENT_VERSION
    rule_version: str = RULE_VERSION


CROP_DEFINITIONS = {
    BLOOD_GRASS: CropDefinition(
        key=BLOOD_GRASS,
        label="止血草",
        seed_key="item.herb.blood_grass",
        growth_seconds=4 * 60 * 60,
        maintenance_energy=1,
        required_maintenance=1,
        maintained_harvest={"item.herb.blood_grass": 3},
        unmaintained_harvest={"item.herb.blood_grass": 1},
        daily_limit=2,
    ),
    SPIRIT_LEAF: CropDefinition(
        key=SPIRIT_LEAF,
        label="灵叶",
        seed_key="item.herb.spirit_leaf",
        growth_seconds=8 * 60 * 60,
        maintenance_energy=2,
        required_maintenance=2,
        maintained_harvest={"item.herb.spirit_leaf": 3},
        unmaintained_harvest={"item.herb.spirit_leaf": 1},
        daily_limit=1,
        residence_key=COURTYARD,
        random_pool=SPIRIT_LEAF_HARVEST_POOL,
    ),
}

CROP_ALIASES = {
    "止血草": BLOOD_GRASS,
    "血草": BLOOD_GRASS,
    "blood_grass": BLOOD_GRASS,
    "灵叶": SPIRIT_LEAF,
    "spirit_leaf": SPIRIT_LEAF,
}


def crop_definition(value: str | None = None) -> CropDefinition:
    key = CROP_ALIASES.get((value or "止血草").strip(), value or BLOOD_GRASS)
    try:
        return CROP_DEFINITIONS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported crop key: {value}") from exc


def spirit_leaf_array_sand_roll(operation_id: str) -> int:
    """Return the frozen 0/1副产物 roll for a spirit-leaf planting."""

    digest = hashlib.blake2b(
        f"{SPIRIT_LEAF_HARVEST_POOL}:{operation_id}".encode("utf-8"), digest_size=2
    ).digest()
    return int.from_bytes(digest, "big") % 2


COMMISSION_HERB_SUPPLY = "town_commission.herb_supply"
COMMISSION_REPAIR_TOOLS = "town_commission.repair_tools"
COMMISSION_MEAL_SERVICE = "town_commission.meal_service"

TOWN_COMMISSION_DEFINITIONS = {
    COMMISSION_HERB_SUPPLY: TownCommissionDefinition(
        key=COMMISSION_HERB_SUPPLY,
        label="止血草供应",
        inputs={"item.herb.blood_grass": 3},
        reward_stones=18,
        local_reputation=3,
        service_reputation=1,
        stock=200,
    ),
    COMMISSION_REPAIR_TOOLS: TownCommissionDefinition(
        key=COMMISSION_REPAIR_TOOLS,
        label="工具修缮",
        inputs={"item.mat.wood": 2, "item.ore.ironstone": 1},
        reward_stones=25,
        local_reputation=4,
        service_reputation=1,
        stock=120,
    ),
    COMMISSION_MEAL_SERVICE: TownCommissionDefinition(
        key=COMMISSION_MEAL_SERVICE,
        label="灵米饭供应",
        inputs={"item.food.spirit_rice": 2},
        reward_stones=20,
        local_reputation=3,
        service_reputation=1,
        stock=150,
    ),
}

COMMISSION_ALIASES = {
    "止血草供应": COMMISSION_HERB_SUPPLY,
    "草药供应": COMMISSION_HERB_SUPPLY,
    "工具修缮": COMMISSION_REPAIR_TOOLS,
    "灵米饭供应": COMMISSION_MEAL_SERVICE,
    "灵米饭": COMMISSION_MEAL_SERVICE,
}


def commission_definition(value: str | None = None) -> TownCommissionDefinition:
    key = COMMISSION_ALIASES.get((value or "").strip(), (value or "").strip())
    try:
        return TOWN_COMMISSION_DEFINITIONS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported commission key: {value}") from exc


PROJECT_TOWN_WELL = "project.town_well"
PROJECT_MARKET_ROAD = "project.market_road"
PROJECT_HERB_GARDEN = "project.herb_garden"
PROJECT_CONTENT_VERSION = "content-0.2"
PROJECT_RULE_VERSION = "livelihood-0.2.0"
TRANSPORT_TICKET = "item.token.transport_coupon"
HERB_SEED_BUNDLE = "item.seed.herb_bundle"


@dataclass(frozen=True, slots=True)
class PublicProjectDefinition:
    key: str
    label: str
    requirements: dict[str, int]
    contribution_resources: tuple[str, ...]
    effect_key: str
    reward: dict[str, int | str]
    content_version: str = PROJECT_CONTENT_VERSION
    rule_version: str = PROJECT_RULE_VERSION


PUBLIC_PROJECT_DEFINITIONS = {
    PROJECT_TOWN_WELL: PublicProjectDefinition(
        key=PROJECT_TOWN_WELL,
        label="新镇灵井",
        requirements={"item.mat.wood": 100},
        contribution_resources=("item.mat.wood",),
        effect_key="town_commission.stock_bonus",
        reward={"spirit_stones": 30, "local_reputation": 5},
    ),
    PROJECT_MARKET_ROAD: PublicProjectDefinition(
        key=PROJECT_MARKET_ROAD,
        label="商路修缮",
        requirements={"item.material.cloud_iron": 60, "currency.spirit_stone": 3000},
        contribution_resources=("item.material.cloud_iron", "currency.spirit_stone"),
        effect_key="route.delay_weight_reduction",
        reward={"service_reputation": 3, "item": TRANSPORT_TICKET},
    ),
    PROJECT_HERB_GARDEN: PublicProjectDefinition(
        key=PROJECT_HERB_GARDEN,
        label="百草园",
        requirements={"item.herb.spirit_leaf": 120},
        contribution_resources=("item.herb.spirit_leaf",),
        effect_key="town_commission.herb_reward_bonus",
        reward={"item": HERB_SEED_BUNDLE},
    ),
}

PROJECT_ALIASES = {
    "灵井": PROJECT_TOWN_WELL,
    "新镇灵井": PROJECT_TOWN_WELL,
    "project.town_well": PROJECT_TOWN_WELL,
    "商路": PROJECT_MARKET_ROAD,
    "商路修缮": PROJECT_MARKET_ROAD,
    "project.market_road": PROJECT_MARKET_ROAD,
    "百草园": PROJECT_HERB_GARDEN,
    "灵草园": PROJECT_HERB_GARDEN,
    "project.herb_garden": PROJECT_HERB_GARDEN,
}


def project_definition(value: str | None = None) -> PublicProjectDefinition:
    key = PROJECT_ALIASES.get((value or "").strip(), (value or "").strip())
    try:
        return PUBLIC_PROJECT_DEFINITIONS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported project key: {value}") from exc


def weekly_project_key(week_key: str) -> str:
    """Choose one deterministic project for a town's weekly rotation."""

    import hashlib

    digest = hashlib.blake2b(week_key.encode("utf-8"), digest_size=2).digest()
    keys = tuple(PUBLIC_PROJECT_DEFINITIONS)
    return keys[int.from_bytes(digest, "big") % len(keys)]


__all__ = [
    "BLOOD_GRASS",
    "SPIRIT_LEAF",
    "SPIRIT_LEAF_HARVEST_POOL",
    "CONTENT_VERSION",
    "COURTYARD",
    "CROP_DEFINITIONS",
    "CROP_ALIASES",
    "COMMISSION_ALIASES",
    "COMMISSION_HERB_SUPPLY",
    "COMMISSION_MEAL_SERVICE",
    "COMMISSION_REPAIR_TOOLS",
    "RULE_VERSION",
    "TOWN_COMMISSION_DEFINITIONS",
    "TownCommissionDefinition",
    "TOWN_ROOM",
    "CropDefinition",
    "ResidenceDefinition",
    "crop_definition",
    "spirit_leaf_array_sand_roll",
    "commission_definition",
    "residence_definition",
    "HERB_SEED_BUNDLE",
    "PROJECT_ALIASES",
    "PROJECT_CONTENT_VERSION",
    "PROJECT_HERB_GARDEN",
    "PROJECT_MARKET_ROAD",
    "PROJECT_RULE_VERSION",
    "PROJECT_TOWN_WELL",
    "PUBLIC_PROJECT_DEFINITIONS",
    "PublicProjectDefinition",
    "TRANSPORT_TICKET",
    "project_definition",
    "weekly_project_key",
]
