"""Pure rules for residence and the first livelihood crop slice."""

from __future__ import annotations


from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content
from ..rewards.rules import local_reputation_maximum
from ..utils.randomness import deterministic_integer


TOWN_ROOM = "residence.town_room"
COURTYARD = "residence.courtyard"
_STAGE_ORDER = {"mortal": 0, "seeker": 1, "cultivator": 2}


@dataclass(frozen=True, slots=True)
class ResidenceDefinition:
    key: str
    label: str
    rent_cost: int
    lease_days: int
    required_stage: str
    required_local_reputation: int = 0
    plot_count: int = 0
    local_reputation_key: str | None = None
    aliases: tuple[str, ...] = ()


def _identity(row: dict[str, Any], record_type: str) -> tuple[str, str, tuple[str, ...]]:
    key, label = row.get("key"), row.get("name")
    if not isinstance(key, str) or not key or not isinstance(label, str) or not label.strip():
        raise ContentError(f"{record_type} requires key and name")
    aliases = row.get("aliases", [])
    if not isinstance(aliases, list) or any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
        raise ContentError(f"{record_type} {key} aliases must be non-empty strings")
    return key, label.strip(), tuple(alias.strip() for alias in aliases)


def _item_reference(bundle: ContentBundle, key: Any, owner: str) -> str:
    if not isinstance(key, str) or not key or not bundle.has("item", key, include_locked=False):
        raise ContentError(f"{owner} references an unknown item")
    return key


def _harvest_map(
    bundle: ContentBundle,
    owner: str,
    raw: Any,
) -> tuple[dict[str, int], dict[str, tuple[int, int]]]:
    if not isinstance(raw, list) or not raw:
        raise ContentError(f"{owner} harvest must be a non-empty list")
    fixed: dict[str, int] = {}
    ranges: dict[str, tuple[int, int]] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise ContentError(f"{owner} harvest entry must be an object")
        item_key = _item_reference(bundle, entry.get("item_key"), owner)
        if item_key in fixed or item_key in ranges:
            raise ContentError(f"{owner} contains duplicate harvest item")
        quantity = entry.get("quantity")
        quantity_range = entry.get("quantity_range")
        if quantity is not None and quantity_range is not None:
            raise ContentError(f"{owner} harvest entry cannot define quantity and quantity_range")
        if quantity is not None:
            if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
                raise ContentError(f"{owner} harvest quantities must be positive integers")
            fixed[item_key] = quantity
            continue
        if (
            not isinstance(quantity_range, list)
            or len(quantity_range) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) for value in quantity_range)
            or quantity_range[0] < 0
            or quantity_range[1] < quantity_range[0]
        ):
            raise ContentError(f"{owner} has an invalid harvest quantity range")
        ranges[item_key] = (quantity_range[0], quantity_range[1])
    return fixed, ranges


def _resolve_definition(
    definitions: dict[str, Any],
    value: str | None,
    default_key: str,
    record_type: str,
) -> Any:
    normalized = (value or default_key).strip()
    selectors = {
        selector: definition.key
        for definition in definitions.values()
        for selector in (definition.key, definition.label, *definition.aliases)
    }
    try:
        return definitions[selectors[normalized]]
    except KeyError as exc:
        raise ValueError(f"unsupported {record_type} key: {value}") from exc


def residence_definitions(content: ContentBundle | None = None) -> dict[str, ResidenceDefinition]:
    bundle = content if content is not None else _default_livelihood_content()
    result: dict[str, ResidenceDefinition] = {}
    selectors: dict[str, str] = {}
    for row in bundle.list("livelihood", include_locked=False):
        if row.get("record_type") != "residence":
            continue
        key, label, aliases = _identity(row, "residence")
        rent = row.get("rent")
        capacity = row.get("capacity")
        requirements = row.get("requirements")
        if not isinstance(rent, dict) or rent.get("currency_key") != "currency.spirit_stone":
            raise ContentError(f"residence {key} has an unsupported rent")
        amount = rent.get("amount")
        periods = [name for name in ("period_days", "period_business_days") if name in rent]
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0 or len(periods) != 1:
            raise ContentError(f"residence {key} has invalid rent values")
        lease_days = rent[periods[0]]
        if isinstance(lease_days, bool) or not isinstance(lease_days, int) or lease_days <= 0:
            raise ContentError(f"residence {key} has an invalid lease period")
        if not isinstance(capacity, dict):
            raise ContentError(f"residence {key} requires capacity")
        plots = capacity.get("plots")
        if isinstance(plots, bool) or not isinstance(plots, int) or plots < 0:
            raise ContentError(f"residence {key} has an invalid plot count")
        if not isinstance(requirements, list) or not requirements:
            raise ContentError(f"residence {key} requires requirements")
        required_stage = "mortal"
        required_local_reputation = 0
        reputation_key: str | None = None
        for requirement in requirements:
            if not isinstance(requirement, dict):
                raise ContentError(f"residence {key} has an invalid requirement")
            requirement_type = requirement.get("type")
            if requirement_type == "stage_min":
                if not isinstance(requirement.get("stage"), str) or not requirement["stage"]:
                    raise ContentError(f"residence {key} has an invalid stage requirement")
                if requirement["stage"] not in _STAGE_ORDER:
                    raise ContentError(f"residence {key} has an unsupported stage requirement")
                required_stage = requirement["stage"]
            elif requirement_type == "reputation":
                reputation_key = requirement.get("reputation_key")
                minimum = requirement.get("min")
                if not isinstance(reputation_key, str) or isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 0:
                    raise ContentError(f"residence {key} has an invalid reputation requirement")
                local_reputation_maximum(reputation_key, bundle)
                required_local_reputation = minimum
            else:
                raise ContentError(f"residence {key} has an unsupported requirement")
        definition = ResidenceDefinition(
            key=key,
            label=label,
            rent_cost=amount,
            lease_days=lease_days,
            required_stage=required_stage,
            required_local_reputation=required_local_reputation,
            plot_count=plots,
            local_reputation_key=reputation_key,
            aliases=aliases,
        )
        if key in result:
            raise ContentError(f"duplicate residence key: {key}")
        for selector in (key, label, *aliases):
            if selector in selectors:
                raise ContentError(f"duplicate residence name or alias: {selector}")
            selectors[selector] = key
        result[key] = definition
    if not result:
        raise ContentError("no active residence records")
    return result


def residence_definition(value: str | None = None, content: ContentBundle | None = None) -> ResidenceDefinition:
    return _resolve_definition(residence_definitions(content), value, TOWN_ROOM, "residence")


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
    maintained_harvest_ranges: dict[str, tuple[int, int]] | None = None
    reputation_key: str | None = None
    reputation_delta: int = 0
    reputation_maximum: int | None = None
    seed_quantity: int = 1
    aliases: tuple[str, ...] = ()


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


def crop_definitions(content: ContentBundle | None = None) -> dict[str, CropDefinition]:
    bundle = content if content is not None else _default_livelihood_content()
    residences = residence_definitions(bundle)
    result: dict[str, CropDefinition] = {}
    selectors: dict[str, str] = {}
    for row in bundle.list("livelihood", include_locked=False):
        if row.get("record_type") != "crop":
            continue
        key, label, aliases = _identity(row, "crop")
        seed = row.get("seed")
        if not isinstance(seed, dict):
            raise ContentError(f"crop {key} requires seed")
        seed_key = _item_reference(bundle, seed.get("item_key"), f"crop {key} seed")
        seed_quantity = seed.get("quantity")
        if isinstance(seed_quantity, bool) or not isinstance(seed_quantity, int) or seed_quantity <= 0:
            raise ContentError(f"crop {key} has an invalid seed quantity")
        growth_seconds = row.get("growth_seconds")
        daily_limit = row.get("daily_limit")
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in (growth_seconds, daily_limit)):
            raise ContentError(f"crop {key} has invalid growth or daily limit")
        maintenance = row.get("maintenance")
        if not isinstance(maintenance, dict):
            raise ContentError(f"crop {key} requires maintenance")
        energy, required = maintenance.get("energy"), maintenance.get("minimum_count")
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (energy, required)):
            raise ContentError(f"crop {key} has invalid maintenance values")
        maintained, ranges = _harvest_map(bundle, f"crop {key}", row.get("harvest"))
        unmaintained, unmaintained_ranges = _harvest_map(bundle, f"crop {key} unmaintained", row.get("unmaintained_harvest"))
        if unmaintained_ranges:
            raise ContentError(f"crop {key} unmaintained harvest cannot be random")
        requirements = row.get("requirements", [])
        if not isinstance(requirements, list):
            raise ContentError(f"crop {key} requirements must be a list")
        residence_key: str | None = None
        for requirement in requirements:
            if not isinstance(requirement, dict):
                raise ContentError(f"crop {key} has an invalid requirement")
            if requirement.get("type") == "residence_key":
                residence_key = requirement.get("value")
                if not isinstance(residence_key, str) or residence_key not in residences:
                    raise ContentError(f"crop {key} references an unknown residence")
            elif requirement.get("type") == "residence_plot":
                if requirement.get("status") != "active":
                    raise ContentError(f"crop {key} has an invalid plot requirement")
            else:
                raise ContentError(f"crop {key} has an unsupported requirement")
        random_pool = row.get("random_pool")
        if ranges and (not isinstance(random_pool, str) or not random_pool):
            raise ContentError(f"crop {key} random harvest requires random_pool")
        reputation = row.get("reputation")
        reputation_key: str | None = None
        reputation_delta = 0
        reputation_maximum: int | None = None
        if reputation is not None:
            if not isinstance(reputation, dict):
                raise ContentError(f"crop {key} reputation must be an object")
            reputation_key = reputation.get("key")
            reputation_delta = reputation.get("amount")
            if not isinstance(reputation_key, str) or isinstance(reputation_delta, bool) or not isinstance(reputation_delta, int) or reputation_delta < 0:
                raise ContentError(f"crop {key} has invalid reputation")
            reputation_maximum = local_reputation_maximum(reputation_key, bundle)
        definition = CropDefinition(
            key=key,
            label=label,
            seed_key=seed_key,
            growth_seconds=growth_seconds,
            maintenance_energy=energy,
            required_maintenance=required,
            maintained_harvest=maintained,
            unmaintained_harvest=unmaintained,
            daily_limit=daily_limit,
            residence_key=residence_key,
            random_pool=random_pool,
            maintained_harvest_ranges=ranges,
            reputation_key=reputation_key,
            reputation_delta=reputation_delta,
            reputation_maximum=reputation_maximum,
            seed_quantity=seed_quantity,
            aliases=aliases,
        )
        if key in result:
            raise ContentError(f"duplicate crop key: {key}")
        for selector in (key, label, *aliases):
            if selector in selectors:
                raise ContentError(f"duplicate crop name or alias: {selector}")
            selectors[selector] = key
        result[key] = definition
    if not result:
        raise ContentError("no active crop records")
    return result


def crop_definition(value: str | None = None, content: ContentBundle | None = None) -> CropDefinition:
    return _resolve_definition(crop_definitions(content), value, BLOOD_GRASS, "crop")


def crop_harvest_bonus(crop: CropDefinition, operation_id: str) -> dict[str, int]:
    """Freeze each configured random harvest quantity from the planting operation."""

    if not crop.maintained_harvest_ranges or not crop.random_pool:
        return {}
    result: dict[str, int] = {}
    ranges = tuple(crop.maintained_harvest_ranges.items())
    for item_key, (minimum, maximum) in ranges:
        seed = f"{crop.random_pool}:{operation_id}"
        if len(ranges) > 1:
            seed = f"{seed}:{item_key}"
        quantity = minimum + deterministic_integer(seed, maximum - minimum + 1)
        if quantity:
            result[item_key] = quantity
    return result


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
    description: str
    effect_description: str
    requirements: dict[str, int]
    contribution_resources: tuple[str, ...]
    resource_labels: dict[str, str]
    reward_labels: dict[str, str]
    effect_key: str
    reward: dict[str, int | str]
    local_reputation_key: str | None = None
    reputation_location_key: str | None = None
    local_reputation_maximum: int = 0
    required_faction: str | None = None
    required_faction_reputation: int = 0
    required_sect_level: int = 0
    required_access_key: str | None = None
    aliases: tuple[str, ...] = ()
    service_sources: tuple["ProjectServiceSource", ...] = ()
    codex_entry_key: str | None = None
    codex_entry_label: str | None = None


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
        effect_desc = row.get("effect_desc")
        if not isinstance(effect_desc, str) or not effect_desc.strip():
            raise ContentError(f"public project {key} requires effect_desc")
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
        reward_labels: dict[str, str] = {}
        for reward_key, reward_value in reward.items():
            if reward_key == "item":
                if not isinstance(reward_value, str) or not bundle.has("item", reward_value, include_locked=False):
                    raise ContentError(f"public project {key} has invalid reward item")
                normalized_reward[reward_key] = reward_value
                reward_labels[reward_value] = bundle.label("item", reward_value)
            elif reward_key in {"spirit_stones", "local_reputation", "service_reputation"}:
                if isinstance(reward_value, bool) or not isinstance(reward_value, int) or reward_value < 0:
                    raise ContentError(f"public project {key} has invalid reward amount")
                normalized_reward[reward_key] = reward_value
                reward_labels[reward_key] = {
                    "spirit_stones": "灵石",
                    "local_reputation": "地方名望",
                    "service_reputation": "行旅声望",
                }[reward_key]
            else:
                raise ContentError(f"public project {key} has unsupported reward {reward_key}")
        if not normalized_reward or not any(
            isinstance(value, int) and value > 0 for value in normalized_reward.values()
        ) and "item" not in normalized_reward:
            raise ContentError(f"public project {key} requires a non-empty reward")
        aliases = row.get("aliases", [])
        if not isinstance(aliases, list) or any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
            raise ContentError(f"public project {key} aliases must be non-empty strings")
        codex_entry_key = row.get("codex_entry_key")
        codex_entry_label: str | None = None
        if codex_entry_key is not None:
            if not isinstance(codex_entry_key, str) or not codex_entry_key:
                raise ContentError(f"public project {key} has invalid codex_entry_key")
            try:
                codex_entry = bundle.require("codex_entry", codex_entry_key, include_locked=False)
            except KeyError as exc:
                raise ContentError(
                    f"public project {key} references inactive codex entry {codex_entry_key!r}"
                ) from exc
            codex_entry_label = str(codex_entry["name"]).strip()
        local_reputation_key = row.get("local_reputation_key")
        reputation_location_key = row.get("reputation_location_key")
        local_reputation = normalized_reward.get("local_reputation", 0)
        local_maximum = 0
        if local_reputation:
            if (
                not isinstance(local_reputation_key, str)
                or not isinstance(reputation_location_key, str)
                or not reputation_location_key
                or local_reputation_key != f"local.{reputation_location_key}"
            ):
                raise ContentError(
                    f"public project {key} requires matching local_reputation_key and reputation_location_key"
                )
            try:
                local_maximum = local_reputation_maximum(
                    local_reputation_key, bundle
                )
            except ContentError as exc:
                raise ContentError(f"public project {key} has invalid reputation location: {exc}") from exc
            reward_labels[local_reputation_key] = f"{bundle.label('location', reputation_location_key)}名望"
            reward_labels.pop("local_reputation", None)
        elif local_reputation_key is not None or reputation_location_key is not None:
            raise ContentError(f"public project {key} has reputation location without a local reputation reward")
        permission_fields = {
            "required_faction": row.get("required_faction"),
            "required_access_key": row.get("required_access_key"),
        }
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
        resource_labels = {
            resource: (
                "灵石"
                if resource == "currency.spirit_stone"
                else bundle.label("item", resource)
            )
            for resource in requirements
        }
        selector_values = {key, label.strip(), *(alias.strip() for alias in aliases)}
        if selectors & selector_values or key in result:
            raise ContentError(f"public project {key} has duplicate key or alias")
        selectors.update(selector_values)
        result[key] = PublicProjectDefinition(
            key=key,
            label=label.strip(),
            description=desc.strip(),
            effect_description=effect_desc.strip(),
            requirements=requirements,
            contribution_resources=tuple(str(item) for item in resources),
            resource_labels=resource_labels,
            reward_labels=reward_labels,
            effect_key=effect_key,
            reward=normalized_reward,
            local_reputation_key=local_reputation_key,
            reputation_location_key=reputation_location_key,
            local_reputation_maximum=local_maximum,
            required_faction=permission_fields["required_faction"],
            required_faction_reputation=numeric["required_faction_reputation"],
            required_sect_level=numeric["required_sect_level"],
            required_access_key=permission_fields["required_access_key"],
            aliases=tuple(alias.strip() for alias in aliases),
            service_sources=tuple(service_sources),
            codex_entry_key=codex_entry_key,
            codex_entry_label=codex_entry_label,
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


def project_resource_key(value: str | None) -> str | None:
    normalized = (value or "").strip()
    if not normalized:
        return None
    return {
        "木材": "item.mat.wood",
        "云铁": "item.material.cloud_iron",
        "灵石": "currency.spirit_stone",
        "灵叶": "item.herb.spirit_leaf",
        "灵米": "item.food.coarse_spirit_rice",
        "灵米饭": "item.food.coarse_spirit_rice",
        "血草": "item.herb.blood_grass",
        "阵砂": "item.mat.array_sand",
        "疗伤丹": "item.pill.healing_low",
    }.get(normalized, normalized)


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
    "TownCommissionDefinition",
    "TOWN_ROOM",
    "CropDefinition",
    "ResidenceDefinition",
    "crop_definition",
    "crop_definitions",
    "crop_harvest_bonus",
    "commission_definition",
    "resolve_commission_key",
    "town_commission_definitions",
    "residence_definition",
    "residence_definitions",
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
    "project_resource_key",
    "project_service_source",
    "weekly_project_key",
]
