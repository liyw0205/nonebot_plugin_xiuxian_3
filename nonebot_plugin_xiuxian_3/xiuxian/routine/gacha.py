"""Content-backed deterministic fate-pool rules."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content
from ..utils.randomness import deterministic_integer, deterministic_weighted_choice


FATE_POOL_KEY = "gacha.fate.basic"


@dataclass(frozen=True, slots=True)
class FateRewardDefinition:
    key: str
    label: str
    rarity: str
    weight: int
    min_quantity: int
    max_quantity: int

    def quantity(self, seed: str, draw_index: int) -> int:
        if self.min_quantity == self.max_quantity:
            return self.min_quantity
        span = self.max_quantity - self.min_quantity + 1
        return self.min_quantity + deterministic_integer(
            f"{seed}:quantity:{draw_index}", span, digest_size=8
        )


@dataclass(frozen=True, slots=True)
class FatePoolDefinition:
    key: str
    content_key: str
    name: str
    operation: str
    single_cost: int
    ten_cost: int
    ticket_key: str | None
    ticket_quantity: int
    pity_limit: int
    entries: tuple[FateRewardDefinition, ...]
    required_realm: str | None = None
    required_layer: int = 0
    required_service_reputation: int | None = None

    @property
    def rare_entries(self) -> tuple[FateRewardDefinition, ...]:
        return tuple(entry for entry in self.entries if entry.rarity == "rare")

    def snapshot(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "content_key": self.content_key,
            "name": self.name,
            "operation": self.operation,
            "draw_costs": {
                "single": {
                    "spirit_stones": self.single_cost,
                    **(
                        {"ticket_key": self.ticket_key, "ticket_quantity": self.ticket_quantity}
                        if self.ticket_key
                        else {}
                    ),
                },
                "ten": {"spirit_stones": self.ten_cost},
            },
            "pity_limit": self.pity_limit,
            "entries": [
                {
                    "item_key": entry.key,
                    "label": entry.label,
                    "rarity": entry.rarity,
                    "weight": entry.weight,
                    "quantity_range": [entry.min_quantity, entry.max_quantity],
                }
                for entry in self.entries
            ],
            "admission": {
                "realm": (
                    {"key": self.required_realm, "min_layer": self.required_layer}
                    if self.required_realm
                    else None
                ),
                "service_reputation": self.required_service_reputation,
            },
        }


@dataclass(frozen=True, slots=True)
class FateDraw:
    key: str
    label: str
    rarity: str
    quantity: int
    guaranteed: bool = False


def fate_pool_definitions(content: ContentBundle | None = None) -> tuple[FatePoolDefinition, ...]:
    bundle = content or bundled_content()
    definitions: list[FatePoolDefinition] = []
    for row in bundle.list("reward", include_locked=True):
        if row.get("operation") != "routine.roll_fate_pool" or "pool_key" not in row:
            continue
        definitions.append(_parse_pool(row, bundle))
    if not definitions:
        raise ContentError("no fate pool content is registered")
    return tuple(definitions)


def fate_pool_definition(
    pool_key: str,
    content: ContentBundle | None = None,
    *,
    include_locked: bool = False,
) -> FatePoolDefinition:
    bundle = content or bundled_content()
    for row in bundle.list("reward", include_locked=True):
        if row.get("operation") == "routine.roll_fate_pool" and row.get("pool_key") == pool_key:
            if not include_locked and row.get("status") not in {"active", "open"}:
                raise ContentError(f"fate pool is not open: {pool_key}")
            return _parse_pool(row, bundle)
    raise ContentError(f"fate pool is not registered: {pool_key}")


def resolve_fate_pool_key(
    value: str,
    content: ContentBundle | None = None,
    *,
    include_locked: bool = False,
) -> str:
    normalized = (value or "").strip()
    if not normalized:
        return FATE_POOL_KEY
    bundle = content or bundled_content()
    matches: list[str] = []
    for row in bundle.list("reward", include_locked=include_locked):
        if row.get("operation") != "routine.roll_fate_pool":
            continue
        aliases = row.get("aliases", [])
        if not isinstance(aliases, list) or any(not isinstance(alias, str) for alias in aliases):
            raise ContentError(f"fate pool {row.get('pool_key')} aliases must be strings")
        if normalized in {str(row.get("pool_key")), str(row.get("name")), *aliases}:
            matches.append(str(row["pool_key"]))
    if len(matches) != 1:
        raise ValueError(f"unknown or ambiguous fate pool: {value}")
    return matches[0]


def _parse_pool(row: dict[str, Any], bundle: ContentBundle) -> FatePoolDefinition:
    content_key = row.get("key")
    pool_key = row.get("pool_key")
    name = row.get("name")
    operation = row.get("operation")
    if not all(isinstance(value, str) and value for value in (content_key, pool_key, name, operation)):
        raise ContentError("fate pool requires key, pool_key, name and operation")
    costs = row.get("draw_costs")
    if not isinstance(costs, dict):
        raise ContentError(f"fate pool {pool_key} draw_costs must be an object")
    single_cost, ticket_key, ticket_quantity = _parse_cost(costs.get("single"), pool_key, "single", bundle)
    ten_cost, _, _ = _parse_cost(costs.get("ten"), pool_key, "ten", bundle, ticket_allowed=False)
    pity_limit = row.get("pity_limit")
    if isinstance(pity_limit, bool) or not isinstance(pity_limit, int) or pity_limit < 1:
        raise ContentError(f"fate pool {pool_key} has invalid pity_limit")
    raw_entries = row.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ContentError(f"fate pool {pool_key} requires entries")
    entries: list[FateRewardDefinition] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            raise ContentError(f"fate pool {pool_key} entry {index} must be an object")
        key, label, rarity = raw.get("item_key"), raw.get("label"), raw.get("rarity")
        weight = raw.get("weight")
        quantity_range = raw.get("quantity_range")
        if (
            not isinstance(key, str)
            or not isinstance(label, str)
            or not label.strip()
            or rarity not in {"common", "rare"}
            or isinstance(weight, bool)
            or not isinstance(weight, int)
            or weight <= 0
            or not isinstance(quantity_range, list)
            or len(quantity_range) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) for value in quantity_range)
            or quantity_range[0] <= 0
            or quantity_range[1] < quantity_range[0]
            or key in seen
        ):
            raise ContentError(f"fate pool {pool_key} entry {index} is invalid")
        _validate_reward_key(bundle, pool_key, key)
        seen.add(key)
        entries.append(FateRewardDefinition(key, label.strip(), rarity, weight, quantity_range[0], quantity_range[1]))
    if not any(entry.rarity == "rare" for entry in entries):
        raise ContentError(f"fate pool {pool_key} requires a rare entry")
    admission = row.get("admission", {})
    if not isinstance(admission, dict):
        raise ContentError(f"fate pool {pool_key} admission must be an object")
    realm = admission.get("realm")
    required_realm: str | None = None
    required_layer = 0
    if realm is not None:
        if not isinstance(realm, dict) or not isinstance(realm.get("key"), str):
            raise ContentError(f"fate pool {pool_key} admission realm is invalid")
        required_realm = realm["key"]
        required_layer = realm.get("min_layer", 1)
        if isinstance(required_layer, bool) or not isinstance(required_layer, int) or required_layer < 1:
            raise ContentError(f"fate pool {pool_key} admission layer is invalid")
        if not bundle.has("realm", required_realm, include_locked=False):
            raise ContentError(f"fate pool {pool_key} references inactive realm {required_realm}")
    service_reputation = admission.get("service_reputation")
    if service_reputation is not None and (
        isinstance(service_reputation, bool) or not isinstance(service_reputation, int) or service_reputation < 0
    ):
        raise ContentError(f"fate pool {pool_key} service reputation threshold is invalid")
    if required_realm is None and service_reputation is None and pool_key != FATE_POOL_KEY:
        raise ContentError(f"fate pool {pool_key} requires an admission rule")
    return FatePoolDefinition(
        key=pool_key,
        content_key=content_key,
        name=name,
        operation=operation,
        single_cost=single_cost,
        ten_cost=ten_cost,
        ticket_key=ticket_key,
        ticket_quantity=ticket_quantity,
        pity_limit=pity_limit,
        entries=tuple(entries),
        required_realm=required_realm,
        required_layer=required_layer,
        required_service_reputation=service_reputation,
    )


def _parse_cost(
    value: Any,
    pool_key: str,
    draw_kind: str,
    bundle: ContentBundle,
    *,
    ticket_allowed: bool = True,
) -> tuple[int, str | None, int]:
    if not isinstance(value, dict):
        raise ContentError(f"fate pool {pool_key} {draw_kind} cost is invalid")
    amount = value.get("spirit_stones")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ContentError(f"fate pool {pool_key} {draw_kind} cost is invalid")
    ticket_key = value.get("ticket_key")
    ticket_quantity = value.get("ticket_quantity", 0)
    if ticket_key is not None:
        if not ticket_allowed or not isinstance(ticket_key, str) or not ticket_key.startswith("item."):
            raise ContentError(f"fate pool {pool_key} {draw_kind} ticket is invalid")
        if isinstance(ticket_quantity, bool) or not isinstance(ticket_quantity, int) or ticket_quantity <= 0:
            raise ContentError(f"fate pool {pool_key} {draw_kind} ticket quantity is invalid")
        if not bundle.has("item", ticket_key, include_locked=False):
            raise ContentError(f"fate pool {pool_key} references inactive ticket {ticket_key}")
    elif ticket_quantity not in {0, None}:
        raise ContentError(f"fate pool {pool_key} {draw_kind} ticket quantity has no ticket")
    return amount, ticket_key, int(ticket_quantity or 0)


def _validate_reward_key(bundle: ContentBundle, pool_key: str, key: str) -> None:
    forbidden = {
        "resource.dao_fruit_progress",
        "resource.ascension_merit",
        "resource.tribulation_debt",
        "item.tribulation_token",
        "item.ascension_certificate",
        "item.dao_fruit",
        "world_merit",
        "cultivation",
        "total_cultivation",
    }
    if key in forbidden or key.startswith("resource.") or key.startswith("combat."):
        raise ContentError(f"fate pool {pool_key} contains forbidden reward {key}")
    if key.startswith("item.") and not bundle.has("item", key, include_locked=False):
        raise ContentError(f"fate pool {pool_key} references inactive item {key}")
    if key.startswith("local.") and not bundle.has("location", key.removeprefix("local."), include_locked=False):
        raise ContentError(f"fate pool {pool_key} references inactive location {key}")
    if key not in {"spirit_stones"} and not key.startswith(("item.", "local.")):
        raise ContentError(f"fate pool {pool_key} has unsupported reward {key}")


def roll_fate_pool(
    operation_id: str,
    *,
    draw_count: int,
    pity_before: int,
    pool: FatePoolDefinition | str | None = None,
    content: ContentBundle | None = None,
) -> tuple[tuple[FateDraw, ...], int, str]:
    definition = (
        fate_pool_definition(pool, content)
        if isinstance(pool, str)
        else pool or fate_pool_definition(FATE_POOL_KEY, content)
    )
    if draw_count not in {1, 10}:
        raise ValueError("draw_count must be 1 or 10")
    if pity_before < 0 or pity_before >= definition.pity_limit:
        raise ValueError("pity_before is outside the pool range")
    seed = f"{definition.key}:{operation_id}"
    seed_hash = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    rare_entries = definition.rare_entries
    pity = pity_before
    draws: list[FateDraw] = []
    rare_seen = False
    for draw_index in range(draw_count):
        guaranteed = pity >= definition.pity_limit - 1
        if draw_count == 10 and draw_index == draw_count - 1 and not rare_seen:
            guaranteed = True
        candidates = rare_entries if guaranteed else definition.entries
        selected = deterministic_weighted_choice(
            tuple((entry.weight, entry) for entry in candidates),
            f"{seed}:choice:{draw_index}",
        )
        draws.append(
            FateDraw(
                key=selected.key,
                label=selected.label,
                rarity=selected.rarity,
                quantity=selected.quantity(seed, draw_index),
                guaranteed=guaranteed,
            )
        )
        if selected.rarity == "rare":
            rare_seen = True
            pity = 0
        else:
            pity += 1
    return tuple(draws), pity, seed_hash


def reward_totals(draws: tuple[FateDraw, ...]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for draw in draws:
        totals[draw.key] = totals.get(draw.key, 0) + draw.quantity
    return totals


_DEFAULT_BASIC_POOL = fate_pool_definition(FATE_POOL_KEY)
FATE_TICKET = _DEFAULT_BASIC_POOL.ticket_key
FATE_PITY_LIMIT = _DEFAULT_BASIC_POOL.pity_limit
FATE_SINGLE_COST = _DEFAULT_BASIC_POOL.single_cost
FATE_TEN_COST = _DEFAULT_BASIC_POOL.ten_cost
FATE_POOL = _DEFAULT_BASIC_POOL.entries


__all__ = [
    "FATE_PITY_LIMIT",
    "FATE_POOL",
    "FATE_POOL_KEY",
    "FATE_SINGLE_COST",
    "FATE_TEN_COST",
    "FATE_TICKET",
    "FateDraw",
    "FatePoolDefinition",
    "FateRewardDefinition",
    "fate_pool_definition",
    "fate_pool_definitions",
    "resolve_fate_pool_key",
    "reward_totals",
    "roll_fate_pool",
]
