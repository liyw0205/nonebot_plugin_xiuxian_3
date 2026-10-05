"""Content-backed rules for asynchronous dispatch tasks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content
from ..rewards.rules import local_reputation_maximum


CANCEL_WINDOW_SECONDS = 60

TOWN_DELIVERY = "dispatch.town_delivery"
HERB_SEARCH = "dispatch.herb_search"
WORKSHOP_HELP = "dispatch.workshop_help"
DEMON_RELIEF = "dispatch.demon_relief"
BEAST_RELOCATION = "dispatch.beast_relocation"
DAO_SERVICE = "dispatch.dao_service"

_STAGE_ORDER = {"new_user": 0, "mortal": 1, "seeker": 2, "cultivator": 3, "suspended": -1}
_REWARD_KEYS = {"spirit_stones", "service_reputation"}


@dataclass(frozen=True, slots=True)
class DispatchDefinition:
    key: str
    label: str
    description: str
    aliases: tuple[str, ...]
    duration_seconds: int
    daily_limit: int
    costs: tuple[tuple[str, int], ...]
    risk_pool: str
    risk_weights: tuple[tuple[str, int], ...]
    requirement: str
    rewards: tuple[tuple[str, tuple[tuple[str, int | tuple[int, int]], ...]], ...]
    required_stage: str | None = None
    required_intro_flag: str | None = None
    required_realm: str | None = None
    required_layer: int | None = None
    required_service_reputation: int | None = None
    required_permit: str | None = None
    failure_refunds: tuple[tuple[str, int], ...] = ()

    def reward_specs(self, outcome: str) -> dict[str, int | tuple[int, int]]:
        rewards = dict(self.rewards)
        values = dict(rewards.get(outcome, ()))
        if outcome == "delayed" and not values:
            values = dict(rewards.get("success", ()))
        return values


def dispatch_definitions(content: ContentBundle | None = None) -> dict[str, DispatchDefinition]:
    bundle = content or bundled_content()
    definitions: dict[str, DispatchDefinition] = {}
    selectors: dict[str, str] = {}
    for row in bundle.list("livelihood", include_locked=False):
        if row.get("record_type") != "dispatch":
            continue
        definition = _parse_dispatch(row, bundle)
        if definition.key in definitions:
            raise ContentError(f"dispatch {definition.key} is duplicated")
        for selector in (definition.key, definition.label, *definition.aliases):
            if selector in selectors:
                raise ContentError(f"dispatch {definition.key} has a duplicate name or alias")
            selectors[selector] = definition.key
        definitions[definition.key] = definition
    if not definitions:
        raise ContentError("no active dispatch content records")
    return definitions


def resolve_dispatch(value: str | None, content: ContentBundle | None = None) -> DispatchDefinition:
    normalized = (value or "").strip()
    definitions = dispatch_definitions(content)
    selectors = {
        selector: definition
        for definition in definitions.values()
        for selector in (definition.key, definition.label, *definition.aliases)
    }
    try:
        return selectors[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported dispatch: {value}") from exc


def roll_bp(seed: str, salt: str) -> int:
    digest = hashlib.blake2b(f"{seed}:{salt}".encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % 10000


def choose_outcome(definition: DispatchDefinition, seed: str) -> str:
    cursor = roll_bp(seed, "risk")
    for outcome, weight in definition.risk_weights:
        if cursor < weight:
            return outcome
        cursor -= weight
    raise ValueError(f"invalid risk pool: {definition.risk_pool}")


def roll_range(seed: str, key: str, low: int, high: int) -> int:
    if low < 0 or low > high:
        raise ValueError("invalid dispatch reward bounds")
    return low + roll_bp(seed, key) % (high - low + 1)


def reward_for(
    definition: DispatchDefinition,
    seed: str,
    outcome: str,
    content: ContentBundle | None = None,
) -> dict[str, int]:
    del content
    if outcome == "failed":
        return {}
    result: dict[str, int] = {}
    for reward_key, value in definition.reward_specs(outcome).items():
        quantity = value if isinstance(value, int) else roll_range(
            seed, f"{definition.key}:{outcome}:{reward_key}", value[0], value[1]
        )
        if quantity > 0:
            result[reward_key] = quantity
    return result


def _parse_dispatch(row: dict[str, Any], bundle: ContentBundle) -> DispatchDefinition:
    key = _required_string(row.get("key"), "dispatch", "key")
    label = _required_string(row.get("name"), key, "name")
    description = _required_string(row.get("desc"), key, "desc")
    aliases = row.get("aliases", [])
    if not isinstance(aliases, list) or any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
        raise ContentError(f"dispatch {key} aliases must be non-empty strings")
    duration = _positive_int(row.get("duration_seconds"), key, "duration_seconds")
    if not 10 * 60 <= duration <= 12 * 60 * 60:
        raise ContentError(f"dispatch {key} duration is outside the allowed range")
    daily_limit = _positive_int(row.get("daily_limit"), key, "daily_limit")
    costs = _parse_costs(row.get("cost"), key, bundle)
    requirements = row.get("requirements")
    if not isinstance(requirements, dict):
        raise ContentError(f"dispatch {key} requirements must be an object")
    required_stage = requirements.get("stage")
    if required_stage is not None and required_stage not in _STAGE_ORDER:
        raise ContentError(f"dispatch {key} has an unsupported stage requirement")
    intro_flag = requirements.get("intro_flag")
    if intro_flag is not None and (not isinstance(intro_flag, str) or not intro_flag):
        raise ContentError(f"dispatch {key} intro_flag must be a stable key")
    realm = requirements.get("realm")
    required_realm = required_layer = None
    if realm is not None:
        if not isinstance(realm, dict) or not isinstance(realm.get("key"), str) or not realm["key"]:
            raise ContentError(f"dispatch {key} realm requirement is invalid")
        if isinstance(realm.get("min_layer"), bool) or not isinstance(realm.get("min_layer"), int) or realm["min_layer"] < 1:
            raise ContentError(f"dispatch {key} realm layer requirement is invalid")
        required_realm, required_layer = realm["key"], realm["min_layer"]
    service_reputation = requirements.get("service_reputation")
    if service_reputation is not None and (
        isinstance(service_reputation, bool) or not isinstance(service_reputation, int) or service_reputation < 0
    ):
        raise ContentError(f"dispatch {key} service reputation requirement is invalid")
    required_permit = row.get("required_permit", requirements.get("required_permit"))
    if required_permit is not None and (not isinstance(required_permit, str) or not required_permit):
        raise ContentError(f"dispatch {key} required_permit must be a stable key")
    risk = row.get("risk")
    if not isinstance(risk, dict) or not isinstance(risk.get("weights"), dict) or not risk["weights"]:
        raise ContentError(f"dispatch {key} risk weights are required")
    risk_weights = []
    for outcome, weight in risk["weights"].items():
        if not isinstance(outcome, str) or outcome not in {"success", "delayed", "partial", "failed"}:
            raise ContentError(f"dispatch {key} has an unsupported outcome")
        if isinstance(weight, bool) or not isinstance(weight, int) or weight <= 0:
            raise ContentError(f"dispatch {key} risk weights must be positive integers")
        risk_weights.append((outcome, weight))
    if sum(weight for _, weight in risk_weights) != 10000:
        raise ContentError(f"dispatch {key} risk weights must total 10000")
    rewards = _parse_rewards(row.get("rewards"), key, bundle)
    risk_pool = _required_string(row.get("risk_pool"), key, "risk_pool")
    failure_refunds = _parse_refunds(row.get("failure_refunds", {}), key, costs)
    return DispatchDefinition(
        key=key,
        label=label,
        description=description,
        aliases=tuple(alias.strip() for alias in aliases),
        duration_seconds=duration,
        daily_limit=daily_limit,
        costs=tuple(costs.items()),
        risk_pool=risk_pool,
        risk_weights=tuple(risk_weights),
        requirement=_requirement_label(requirements, required_permit, intro_flag, required_realm, required_layer, service_reputation),
        rewards=tuple(rewards.items()),
        required_stage=required_stage,
        required_intro_flag=intro_flag,
        required_realm=required_realm,
        required_layer=required_layer,
        required_service_reputation=service_reputation,
        required_permit=required_permit,
        failure_refunds=tuple(failure_refunds.items()),
    )


def _parse_costs(value: Any, key: str, bundle: ContentBundle) -> dict[str, int]:
    if not isinstance(value, dict) or not value:
        raise ContentError(f"dispatch {key} cost must be a non-empty object")
    result: dict[str, int] = {}
    for cost_key, amount in value.items():
        if not isinstance(cost_key, str) or not cost_key or isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ContentError(f"dispatch {key} has invalid cost")
        if cost_key not in {"stamina", "energy"} and cost_key.startswith("item."):
            try:
                bundle.require("item", cost_key, include_locked=False)
            except KeyError as exc:
                raise ContentError(f"dispatch {key} references inactive cost item {cost_key}") from exc
        elif cost_key not in {"stamina", "energy"}:
            raise ContentError(f"dispatch {key} has unsupported cost {cost_key}")
        result[cost_key] = amount
    return result


def _parse_rewards(value: Any, key: str, bundle: ContentBundle) -> dict[str, dict[str, int | tuple[int, int]]]:
    if not isinstance(value, dict) or not value:
        raise ContentError(f"dispatch {key} rewards must be a non-empty object")
    result: dict[str, dict[str, int | tuple[int, int]]] = {}
    for outcome, entries in value.items():
        if outcome not in {"success", "partial"} or not isinstance(entries, dict) or not entries:
            raise ContentError(f"dispatch {key} has invalid {outcome} rewards")
        parsed: dict[str, int | tuple[int, int]] = {}
        for reward_key, amount in entries.items():
            _validate_reward_key(reward_key, key, bundle)
            if isinstance(amount, int) and not isinstance(amount, bool):
                if amount <= 0:
                    raise ContentError(f"dispatch {key} reward quantities must be positive")
                parsed[reward_key] = amount
                continue
            if (
                not isinstance(amount, dict)
                or set(amount) != {"quantity_range"}
                or not isinstance(amount["quantity_range"], list)
                or len(amount["quantity_range"]) != 2
                or any(isinstance(item, bool) or not isinstance(item, int) for item in amount["quantity_range"])
                or amount["quantity_range"][0] < 0
                or amount["quantity_range"][0] > amount["quantity_range"][1]
            ):
                raise ContentError(f"dispatch {key} reward range is invalid")
            parsed[reward_key] = tuple(amount["quantity_range"])
        result[outcome] = parsed
    return result


def _validate_reward_key(reward_key: Any, dispatch_key: str, bundle: ContentBundle) -> None:
    if not isinstance(reward_key, str) or not reward_key:
        raise ContentError(f"dispatch {dispatch_key} reward key is invalid")
    if reward_key.startswith("item."):
        try:
            bundle.require("item", reward_key, include_locked=False)
        except KeyError as exc:
            raise ContentError(f"dispatch {dispatch_key} references inactive item {reward_key}") from exc
    elif reward_key.startswith("codex."):
        try:
            bundle.require("codex_entry", reward_key, include_locked=False)
        except KeyError as exc:
            raise ContentError(f"dispatch {dispatch_key} references inactive codex {reward_key}") from exc
    elif reward_key.startswith("local."):
        try:
            local_reputation_maximum(reward_key, bundle)
        except (ContentError, ValueError) as exc:
            raise ContentError(f"dispatch {dispatch_key} references invalid local reputation {reward_key}") from exc
    elif reward_key not in _REWARD_KEYS:
        raise ContentError(f"dispatch {dispatch_key} has unsupported reward {reward_key}")


def _parse_refunds(value: Any, key: str, costs: dict[str, int]) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ContentError(f"dispatch {key} failure_refunds must be an object")
    result: dict[str, int] = {}
    for cost_key, amount in value.items():
        if cost_key not in costs or isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0 or amount > costs[cost_key]:
            raise ContentError(f"dispatch {key} has invalid failure refund")
        result[cost_key] = amount
    return result


def _requirement_label(
    requirements: dict[str, Any],
    permit: str | None,
    intro_flag: str | None,
    realm: str | None,
    layer: int | None,
    service_reputation: int | None,
) -> str:
    if permit:
        return permit
    if intro_flag:
        return intro_flag
    if realm and layer is not None and service_reputation is not None:
        return f"{realm}_or_service_reputation_{service_reputation}"
    if realm and layer is not None:
        return f"{realm}_{layer}"
    if service_reputation is not None:
        return f"service_reputation_{service_reputation}"
    return str(requirements.get("stage", ""))


def _required_string(value: Any, owner: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"{owner} requires {field}")
    return value.strip()


def _positive_int(value: Any, owner: str, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"{owner} {field} must be positive")
    return value


DISPATCHES: dict[str, DispatchDefinition] = dispatch_definitions()
ALIASES = {
    alias: definition.key
    for definition in DISPATCHES.values()
    for alias in (definition.label, *definition.aliases)
}


__all__ = [
    "ALIASES",
    "BEAST_RELOCATION",
    "CANCEL_WINDOW_SECONDS",
    "DAO_SERVICE",
    "DEMON_RELIEF",
    "DISPATCHES",
    "DispatchDefinition",
    "HERB_SEARCH",
    "TOWN_DELIVERY",
    "WORKSHOP_HELP",
    "choose_outcome",
    "dispatch_definitions",
    "resolve_dispatch",
    "reward_for",
]
