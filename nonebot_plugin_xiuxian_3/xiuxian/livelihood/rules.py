"""Pure rules for residence and the first livelihood crop slice."""

from __future__ import annotations


import hashlib
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content
from ..rewards.rules import local_reputation_maximum


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


def _commission_identity(row: dict[str, Any]) -> tuple[str, str, tuple[str, ...]]:
    key, label = row.get("key"), row.get("name")
    if not isinstance(key, str) or not key or not isinstance(label, str) or not label.strip():
        raise ContentError(f"commission requires key and name: {key!r}")
    aliases = row.get("aliases", [])
    if not isinstance(aliases, list) or any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
        raise ContentError(f"commission {key} aliases must be non-empty strings")
    return key, label.strip(), tuple(alias.strip() for alias in aliases)


def resolve_commission_key(value: str | None, content: ContentBundle | None = None) -> str:
    """Resolve identity without revalidating rewards of a frozen claim or replay."""

    bundle = content if content is not None else _default_commission_content()
    selectors: dict[str, str] = {}
    for row in bundle.list("livelihood", include_locked=True):
        if row.get("record_type") != "commission":
            continue
        key, label, aliases = _commission_identity(row)
        for selector in {key, label, *aliases}:
            if selector in selectors:
                raise ContentError(f"commission {key} has a duplicate name or alias")
            selectors[selector] = key
    try:
        return selectors[(value or "").strip()]
    except KeyError as exc:
        raise ValueError(f"unsupported commission key: {value}") from exc


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
        key, label, aliases = _commission_identity(row)
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
        reputation_key = reward.get("reputation_key")
        if not isinstance(reputation_key, str) or not reputation_key:
            raise ContentError(f"commission {key} has an invalid reputation key")
        try:
            local_reputation_maximum(reputation_key, bundle)
        except ContentError as exc:
            raise ContentError(
                f"commission {key} references an invalid reputation location"
            ) from exc
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
        selectors_for_row = {key, label, *aliases}
        if selectors & selectors_for_row:
            raise ContentError(f"commission {key} has a duplicate name or alias")
        selectors.update(selectors_for_row)
        result[key] = TownCommissionDefinition(
            key=key,
            label=label,
            inputs={str(item["item_key"]): int(item["quantity"]) for item in inputs},
            reward_stones=amount,
            local_reputation=local_reputation,
            service_reputation=service_reputation,
            stock=stock,
            local_reputation_key=reputation_key,
            duration_seconds=duration,
            aliases=aliases,
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
    aliases: tuple[str, ...] = ()
    service_sources: tuple["ProjectServiceSource", ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectServiceSource:
    """A settled operation that can add contribution without another cost."""

    project_key: str
    service_key: str
    operation_names: tuple[str, ...]
    contribution_points: int
    quantity: int = 1


@lru_cache(maxsize=1)
def _default_livelihood_content() -> ContentBundle:
    return bundled_content()


def _positive_mapping(row: dict[str, Any], field: str, bundle: ContentBundle, key: str) -> dict[str, int]:
    value = row.get(field)
    if not isinstance(value, dict) or not value:
        raise ContentError(f"public project {key} has invalid {field}")
    result: dict[str, int] = {}
    for raw_key, raw_amount in value.items():
        if not isinstance(raw_key, str) or not raw_key:
            raise ContentError(f"public project {key} has invalid {field} key")
        if isinstance(raw_amount, bool) or not isinstance(raw_amount, int) or raw_amount <= 0:
            raise ContentError(f"public project {key} has invalid {field} amount")
        if raw_key != "currency.spirit_stone" and not bundle.has("item", raw_key, include_locked=False):
            raise ContentError(f"public project {key} references unknown item {raw_key}")
        result[raw_key] = raw_amount
    return result


def public_project_definitions(content: ContentBundle | None = None) -> dict[str, PublicProjectDefinition]:
    bundle = content if content is not None else _default_livelihood_content()
    result: dict[str, PublicProjectDefinition] = {}
    selectors: set[str] = set()
    for row in bundle.list("livelihood", include_locked=False):
        if row.get("record_type") != "public_project":
            continue
        key, label, desc = row.get("key"), row.get("name"), row.get("desc")
        if not isinstance(key, str) or not key or not isinstance(label, str) or not label.strip() or not isinstance(desc, str) or not desc.strip():
            raise ContentError(f"public project {key!r} requires key, name and desc")
        requirements = _positive_mapping(row, "requirements", bundle, key)
        resources = row.get("contribution_resources")
        if not isinstance(resources, list) or not resources or any(item not in requirements for item in resources):
            raise ContentError(f"public project {key} has invalid contribution_resources")
        effect_key = row.get("effect_key")
        if not isinstance(effect_key, str) or not effect_key:
            raise ContentError(f"public project {key} has invalid effect_key")
        reward = row.get("reward")
        if not isinstance(reward, dict):
            raise ContentError(f"public project {key} has invalid reward")
        normalized_reward: dict[str, int | str] = {}
        for reward_key, reward_value in reward.items():
            if reward_key == "item":
                if not isinstance(reward_value, str) or not bundle.has("item", reward_value, include_locked=False):
                    raise ContentError(f"public project {key} has invalid reward item")
                normalized_reward[reward_key] = reward_value
            elif reward_key in {"spirit_stones", "local_reputation", "service_reputation"}:
                if isinstance(reward_value, bool) or not isinstance(reward_value, int) or reward_value < 0:
                    raise ContentError(f"public project {key} has invalid reward amount")
                normalized_reward[reward_key] = reward_value
            else:
                raise ContentError(f"public project {key} has unsupported reward {reward_key}")
        aliases = row.get("aliases", [])
        if not isinstance(aliases, list) or any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
            raise ContentError(f"public project {key} aliases must be non-empty strings")
        permission_fields = {
            "local_reputation_key": row.get("local_reputation_key", "local.xuantian.new_town"),
            "required_faction": row.get("required_faction"),
            "required_access_key": row.get("required_access_key"),
        }
        if not isinstance(permission_fields["local_reputation_key"], str) or not permission_fields["local_reputation_key"]:
            raise ContentError(f"public project {key} has invalid local_reputation_key")
        for field in ("required_faction", "required_access_key"):
            if permission_fields[field] is not None and (not isinstance(permission_fields[field], str) or not permission_fields[field]):
                raise ContentError(f"public project {key} has invalid {field}")
        numeric = {
            "required_faction_reputation": row.get("required_faction_reputation", 0),
            "required_sect_level": row.get("required_sect_level", 0),
        }
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in numeric.values()):
            raise ContentError(f"public project {key} has invalid permission threshold")
        service_rows = row.get("service_sources", [])
        if not isinstance(service_rows, list):
            raise ContentError(f"public project {key} service_sources must be a list")
        service_sources: list[ProjectServiceSource] = []
        for source in service_rows:
            if not isinstance(source, dict):
                raise ContentError(f"public project {key} has invalid service source")
            operation_names = source.get("operation_names")
            service_key = source.get("service_key")
            points, quantity = source.get("contribution_points"), source.get("quantity", 1)
            if (
                not isinstance(operation_names, list) or not operation_names
                or any(not isinstance(name, str) or not name for name in operation_names)
                or not isinstance(service_key, str) or not service_key
                or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in (points, quantity))
            ):
                raise ContentError(f"public project {key} has invalid service source")
            service_sources.append(ProjectServiceSource(key, service_key, tuple(operation_names), points, quantity))
        selector_values = {key, label.strip(), *(alias.strip() for alias in aliases)}
        if selectors & selector_values or key in result:
            raise ContentError(f"public project {key} has duplicate key or alias")
        selectors.update(selector_values)
        result[key] = PublicProjectDefinition(
            key=key,
            label=label.strip(),
            requirements=requirements,
            contribution_resources=tuple(str(item) for item in resources),
            effect_key=effect_key,
            reward=normalized_reward,
            local_reputation_key=permission_fields["local_reputation_key"],
            required_faction=permission_fields["required_faction"],
            required_faction_reputation=numeric["required_faction_reputation"],
            required_sect_level=numeric["required_sect_level"],
            required_access_key=permission_fields["required_access_key"],
            aliases=tuple(alias.strip() for alias in aliases),
            service_sources=tuple(service_sources),
        )
    if not result:
        raise ContentError("no active public project content records")
    return result


def project_service_source(
    project_key: str,
    operation_name: str,
    content: ContentBundle | None = None,
) -> ProjectServiceSource | None:
    definition = public_project_definitions(content).get(project_key)
    if definition is None:
        return None
    for source in definition.service_sources:
        if operation_name in source.operation_names:
            return source
    return None


def project_definition(value: str | None = None, content: ContentBundle | None = None) -> PublicProjectDefinition:
    normalized = (value or "").strip()
    for definition in public_project_definitions(content).values():
        if normalized in {definition.key, definition.label, *definition.aliases}:
            return definition
    raise ValueError(f"unsupported project key: {value}")


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
    "resolve_commission_key",
    "town_commission_definitions",
    "residence_definition",
    "HERB_SEED_BUNDLE",
    "PROJECT_DOMAIN_REFUGE",
    "PROJECT_ABYSS_PURIFICATION",
    "PROJECT_ANCESTRAL_HABITAT",
    "PROJECT_HERB_GARDEN",
    "PROJECT_MARKET_ROAD",
    "PROJECT_TOWN_WELL",
    "CONSTRUCTION_COUPON",
    "public_project_definitions",
    "ProjectServiceSource",
    "PublicProjectDefinition",
    "TRANSPORT_TICKET",
    "project_definition",
    "project_service_source",
    "weekly_project_key",
]
