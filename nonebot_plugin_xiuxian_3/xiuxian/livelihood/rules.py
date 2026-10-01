"""Pure rules for residence and the first livelihood crop slice."""

from __future__ import annotations


import hashlib
from dataclasses import dataclass
from functools import lru_cache

from ..content import ContentBundle, ContentError, bundled_content


TOWN_ROOM = "residence.town_room"
COURTYARD = "residence.courtyard"


@dataclass(frozen=True, slots=True)
class ResidenceDefinition:
    key: str
    label: str
    rent_cost: int
    lease_days: int
    required_stage: str
    required_local_reputation: int = 0
    plot_count: int = 0


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
SPIRIT_LEAF_HARVEST_POOL = "livelihood.harvest"


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


@dataclass(frozen=True, slots=True)
class TownCommissionDefinition:
    key: str
    label: str
    inputs: dict[str, int]
    reward_stones: int
    local_reputation: int
    service_reputation: int
    stock: int
    local_reputation_key: str = "local.xuantian.new_town"
    duration_seconds: int = 12 * 60 * 60
    aliases: tuple[str, ...] = ()
    unlock_key: str | None = None
    requirements_any: tuple[dict[str, object], ...] = ()
    stock_bonus_key: str | None = None
    reward_bonus_key: str | None = None


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


@lru_cache(maxsize=1)
def _default_commission_content() -> ContentBundle:
    return bundled_content()


def town_commission_definitions(
    content: ContentBundle | None = None,
) -> dict[str, TownCommissionDefinition]:
    bundle = content if content is not None else _default_commission_content()
    realms = {str(row["key"]) for row in bundle.list("realm", include_locked=False)}
    result: dict[str, TownCommissionDefinition] = {}
    selectors: set[str] = set()
    for row in bundle.list("livelihood", include_locked=False):
        if row.get("record_type") != "commission":
            continue
        key, label = row.get("key"), row.get("name")
        if not isinstance(key, str) or not key or not isinstance(label, str) or not label.strip():
            raise ContentError(f"commission requires key and name: {key!r}")
        inputs = row.get("inputs")
        if (
            not isinstance(inputs, list)
            or not inputs
            or any(
                not isinstance(item, dict)
                or not isinstance(item.get("item_key"), str)
                or not item["item_key"]
                or isinstance(item.get("quantity"), bool)
                or not isinstance(item.get("quantity"), int)
                or item["quantity"] <= 0
                for item in inputs
            )
        ):
            raise ContentError(f"commission {key} has invalid inputs")
        reward = row.get("reward")
        if not isinstance(reward, dict) or reward.get("currency_key") != "currency.spirit_stone":
            raise ContentError(f"commission {key} has an unsupported reward currency")
        amount = reward.get("amount")
        stock = row.get("stock")
        duration = row.get("duration_seconds", 12 * 60 * 60)
        local_reputation = reward.get("reputation", 0)
        service_reputation = reward.get("service_reputation", 0)
        numbers = (amount, stock, duration, local_reputation, service_reputation)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in numbers):
            raise ContentError(f"commission {key} has invalid numeric values")
        if amount < 0 or stock <= 0 or duration <= 0 or local_reputation < 0 or service_reputation < 0:
            raise ContentError(f"commission {key} has out-of-range numeric values")
        reputation_key = reward.get("reputation_key", "local.xuantian.new_town")
        if not isinstance(reputation_key, str) or not reputation_key:
            raise ContentError(f"commission {key} has an invalid reputation key")
        aliases = row.get("aliases", [])
        if not isinstance(aliases, list) or any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
            raise ContentError(f"commission {key} aliases must be non-empty strings")
        unlock_key = row.get("unlock_key")
        if unlock_key is not None and (
            not isinstance(unlock_key, str)
            or not bundle.has("codex_unlock", unlock_key, include_locked=False)
        ):
            raise ContentError(f"commission {key} references an unknown codex unlock")
        requirements_any = row.get("requirements_any", [])
        if not isinstance(requirements_any, list):
            raise ContentError(f"commission {key} requirements_any must be a list")
        for requirement in requirements_any:
            if not isinstance(requirement, dict):
                raise ContentError(f"commission {key} has an invalid requirement")
            if requirement.get("type") == "realm":
                realm_key, layer = requirement.get("realm_key"), requirement.get("min_layer")
                if (
                    realm_key not in realms
                    or isinstance(layer, bool)
                    or not isinstance(layer, int)
                    or layer < 1
                ):
                    raise ContentError(f"commission {key} has an invalid realm requirement")
            elif requirement.get("type") == "local_reputation":
                rep_key, minimum = requirement.get("reputation_key"), requirement.get("minimum")
                if (
                    not isinstance(rep_key, str)
                    or not rep_key
                    or isinstance(minimum, bool)
                    or not isinstance(minimum, int)
                    or minimum <= 0
                ):
                    raise ContentError(f"commission {key} has an invalid reputation requirement")
            else:
                raise ContentError(f"commission {key} has an unsupported requirement")
        stock_bonus_key = row.get("stock_bonus_key")
        reward_bonus_key = row.get("reward_bonus_key")
        if any(
            value is not None and (not isinstance(value, str) or not value)
            for value in (stock_bonus_key, reward_bonus_key)
        ):
            raise ContentError(f"commission {key} has an invalid public-project bonus key")
        selectors_for_row = {key, label.strip(), *(alias.strip() for alias in aliases)}
        if selectors & selectors_for_row:
            raise ContentError(f"commission {key} has a duplicate name or alias")
        selectors.update(selectors_for_row)
        result[key] = TownCommissionDefinition(
            key=key,
            label=label.strip(),
            inputs={str(item["item_key"]): int(item["quantity"]) for item in inputs},
            reward_stones=amount,
            local_reputation=local_reputation,
            service_reputation=service_reputation,
            stock=stock,
            local_reputation_key=reputation_key,
            duration_seconds=duration,
            aliases=tuple(alias.strip() for alias in aliases),
            unlock_key=unlock_key,
            requirements_any=tuple(dict(requirement) for requirement in requirements_any),
            stock_bonus_key=stock_bonus_key,
            reward_bonus_key=reward_bonus_key,
        )
    return result


def commission_definition(
    value: str | None = None,
    content: ContentBundle | None = None,
) -> TownCommissionDefinition:
    normalized = (value or "").strip()
    for definition in town_commission_definitions(content).values():
        if normalized in {definition.key, definition.label, *definition.aliases}:
            return definition
    raise ValueError(f"unsupported commission key: {value}")


PROJECT_TOWN_WELL = "project.town_well"
PROJECT_MARKET_ROAD = "project.market_road"
PROJECT_HERB_GARDEN = "project.herb_garden"
PROJECT_DOMAIN_REFUGE = "project.domain_refuge"
PROJECT_ABYSS_PURIFICATION = "project.abyss_purification"
PROJECT_ANCESTRAL_HABITAT = "project.ancestral_habitat"
TRANSPORT_TICKET = "item.token.transport_coupon"
HERB_SEED_BUNDLE = "item.seed.herb_bundle"
CONSTRUCTION_COUPON = "item.token.construction_coupon"


@dataclass(frozen=True, slots=True)
class PublicProjectDefinition:
    key: str
    label: str
    requirements: dict[str, int]
    contribution_resources: tuple[str, ...]
    effect_key: str
    reward: dict[str, int | str]
    local_reputation_key: str = "local.xuantian.new_town"
    required_faction: str | None = None
    required_faction_reputation: int = 0
    required_sect_level: int = 0
    required_access_key: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectServiceSource:
    """A settled operation that can add contribution without another cost."""

    project_key: str
    service_key: str
    operation_names: tuple[str, ...]
    contribution_points: int
    quantity: int = 1


PROJECT_SERVICE_SOURCES = (
    ProjectServiceSource(
        project_key=PROJECT_DOMAIN_REFUGE,
        service_key="service.transport",
        operation_names=("livelihood.settle_route",),
        contribution_points=20,
    ),
    ProjectServiceSource(
        project_key=PROJECT_ABYSS_PURIFICATION,
        service_key="service.purification",
        operation_names=("production.purify_pollution",),
        contribution_points=15,
    ),
    ProjectServiceSource(
        project_key=PROJECT_ANCESTRAL_HABITAT,
        service_key="service.taming",
        operation_names=("companion.bond", "companion.feed"),
        contribution_points=15,
    ),
    ProjectServiceSource(
        project_key=PROJECT_ANCESTRAL_HABITAT,
        service_key="service.repair",
        operation_names=("companion.rest",),
        contribution_points=15,
    ),
)


def project_service_source(project_key: str, operation_name: str) -> ProjectServiceSource | None:
    for source in PROJECT_SERVICE_SOURCES:
        if source.project_key == project_key and operation_name in source.operation_names:
            return source
    return None


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
    # Authority-gated projects are materialized on demand; the weekly rotation
    # remains limited to the original three projects.
    PROJECT_DOMAIN_REFUGE: PublicProjectDefinition(
        key=PROJECT_DOMAIN_REFUGE,
        label="领域避难所",
        requirements={
            "item.mat.wood": 60,
            "item.food.coarse_spirit_rice": 60,
            "item.pill.healing_low": 20,
        },
        contribution_resources=(
            "item.mat.wood",
            "item.food.coarse_spirit_rice",
            "item.pill.healing_low",
        ),
        effect_key="domain_refuge.low_risk_stock_bonus",
        reward={"local_reputation": 8, "service_reputation": 3, "item": CONSTRUCTION_COUPON},
        local_reputation_key="local.domain_refuge",
        required_sect_level=4,
        required_access_key="access.project.domain_refuge",
    ),
    PROJECT_ABYSS_PURIFICATION: PublicProjectDefinition(
        key=PROJECT_ABYSS_PURIFICATION,
        label="魔渊净化工程",
        requirements={"item.herb.blood_grass": 60, "item.mat.array_sand": 60},
        contribution_resources=("item.herb.blood_grass", "item.mat.array_sand"),
        effect_key="abyss_purification.route_delay_reduction",
        reward={"local_reputation": 8, "service_reputation": 3, "item": CONSTRUCTION_COUPON},
        local_reputation_key="local.abyss_outpost",
        required_faction="demon",
        required_faction_reputation=300,
        required_access_key="access.project.abyss_purification",
    ),
    PROJECT_ANCESTRAL_HABITAT: PublicProjectDefinition(
        key=PROJECT_ANCESTRAL_HABITAT,
        label="祖灵栖地修复",
        requirements={"item.food.coarse_spirit_rice": 60, "item.herb.spirit_leaf": 60},
        contribution_resources=("item.food.coarse_spirit_rice", "item.herb.spirit_leaf"),
        effect_key="ancestral_habitat.commission_stock_bonus",
        reward={"local_reputation": 8, "service_reputation": 3, "item": CONSTRUCTION_COUPON},
        local_reputation_key="local.ancestral_habitat",
        required_faction="beast",
        required_faction_reputation=300,
        required_access_key="access.project.ancestral_habitat",
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
    "领域避难所": PROJECT_DOMAIN_REFUGE,
    "project.domain_refuge": PROJECT_DOMAIN_REFUGE,
    "魔渊净化工程": PROJECT_ABYSS_PURIFICATION,
    "project.abyss_purification": PROJECT_ABYSS_PURIFICATION,
    "祖灵栖地修复": PROJECT_ANCESTRAL_HABITAT,
    "project.ancestral_habitat": PROJECT_ANCESTRAL_HABITAT,
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
    # Reconstruction projects are authority-gated and materialized
    # separately; changing this legacy pool would rewrite historical rotations.
    keys = (PROJECT_TOWN_WELL, PROJECT_MARKET_ROAD, PROJECT_HERB_GARDEN)
    return keys[int.from_bytes(digest, "big") % len(keys)]


__all__ = [
    "BLOOD_GRASS",
    "SPIRIT_LEAF",
    "SPIRIT_LEAF_HARVEST_POOL",
    "COURTYARD",
    "CROP_DEFINITIONS",
    "CROP_ALIASES",
    "TownCommissionDefinition",
    "TOWN_ROOM",
    "CropDefinition",
    "ResidenceDefinition",
    "crop_definition",
    "spirit_leaf_array_sand_roll",
    "commission_definition",
    "town_commission_definitions",
    "residence_definition",
    "HERB_SEED_BUNDLE",
    "PROJECT_ALIASES",
    "PROJECT_DOMAIN_REFUGE",
    "PROJECT_ABYSS_PURIFICATION",
    "PROJECT_ANCESTRAL_HABITAT",
    "PROJECT_HERB_GARDEN",
    "PROJECT_MARKET_ROAD",
    "PROJECT_TOWN_WELL",
    "CONSTRUCTION_COUPON",
    "PUBLIC_PROJECT_DEFINITIONS",
    "PROJECT_SERVICE_SOURCES",
    "ProjectServiceSource",
    "PublicProjectDefinition",
    "TRANSPORT_TICKET",
    "project_definition",
    "project_service_source",
    "weekly_project_key",
]
