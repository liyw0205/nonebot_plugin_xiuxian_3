"""Rules for the staged onboarding guides (content-backed).

Guide tiers, handles and presentation live in ``data/引导/引导.json``
(kind ``guide``): each record declares its stage through ``requirements``, its
player-facing ``label`` and the ``command``/``aliases`` that reach it. The
tables below are derived per call rather than at import, so importing this
module never requires a content bundle to be present.

Graduation stays tied to the mortal lessons: :func:`intro_complete` counts only
guides declared for the ``mortal`` stage, so a realm-gated guide can never
stand in for the onboarding trio.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content

KIND = "guide"

STAGE_NEW_USER = "new_user"
STAGE_MORTAL = "mortal"
STAGE_SEEKER = "seeker"
STAGE_CULTIVATOR = "cultivator"

# The shipped mortal lessons. Kept as literals because callers gate behaviour on
# the specific lesson (spirit-field cultivation requires the gathering lesson).
GUIDE_READ_WORLD = "guide.read_world"
GUIDE_GATHER_BLOOD_GRASS = "guide.gather_blood_grass"
GUIDE_CHOOSE_SERVICE = "guide.choose_service"
INTRO_GUIDES = (
    GUIDE_READ_WORLD,
    GUIDE_GATHER_BLOOD_GRASS,
    GUIDE_CHOOSE_SERVICE,
)

_SUPPORTED_STAGES = (STAGE_NEW_USER, STAGE_MORTAL, STAGE_SEEKER, STAGE_CULTIVATOR)

# Stages where a tier's guides are still offered. The mortal lessons stay usable
# through the ``seeker`` stopover, exactly as before this slice.
_TIER_AVAILABILITY = {
    STAGE_MORTAL: (STAGE_MORTAL, STAGE_SEEKER),
}

SERVICE_LABELS = {
    "alchemy": "炼丹",
    "artifice": "炼器",
    "formation": "布阵",
    "cooking": "烹饪",
}

SERVICE_ALIASES = {
    "炼丹": "alchemy",
    "炼器": "artifice",
    "布阵": "formation",
    "alchemy": "alchemy",
    "artifice": "artifice",
    "formation": "formation",
    "烹饪": "cooking",
    "cooking": "cooking",
}

TRAVEL_DESTINATIONS = {
    "近郊": "xuantian.outskirts",
    "玄天近郊": "xuantian.outskirts",
    "xuantian.outskirts": "xuantian.outskirts",
    "新手城": "xuantian.new_town",
    "青石镇": "xuantian.new_town",
    "xuantian.new_town": "xuantian.new_town",
    "灵泉谷": "xuantian.spirit_field",
    "玄天灵泉谷": "xuantian.spirit_field",
    "xuantian.spirit_field": "xuantian.spirit_field",
}

TRAVEL_LABELS = {
    "xuantian.outskirts": "玄天近郊",
    "xuantian.new_town": "青石镇",
    "xuantian.spirit_field": "灵泉谷",
}

TRAVEL_COSTS = {
    "xuantian.outskirts": 2,
    "xuantian.new_town": 1,
    "xuantian.spirit_field": 4,
}


def guide_definitions(content: ContentBundle | None = None) -> tuple[dict[str, Any], ...]:
    """Return every active guide, in content order, fully validated."""

    return tuple(_definitions(content))


def guide_definition(key: str, content: ContentBundle | None = None) -> dict[str, Any]:
    for definition in _definitions(content):
        if definition["key"] == key:
            return definition
    raise ValueError(f"unsupported guide: {key}")


def guide_labels(content: ContentBundle | None = None) -> dict[str, str]:
    return {definition["key"]: definition["label"] for definition in _definitions(content)}


def guide_commands(content: ContentBundle | None = None) -> dict[str, str]:
    return {definition["key"]: definition["command"] for definition in _definitions(content)}


def guide_alias_map(content: ContentBundle | None = None) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for definition in _definitions(content):
        for selector in (definition["key"], definition["command"], *definition["aliases"]):
            aliases[selector] = definition["key"]
    return aliases


def guides_for_stage(
    stage: str, content: ContentBundle | None = None
) -> tuple[dict[str, Any], ...]:
    """Return the guides a player at ``stage`` may work on, in content order."""

    return tuple(
        definition
        for definition in _definitions(content)
        if stage in _TIER_AVAILABILITY.get(definition["stage"], (definition["stage"],))
    )


def mortal_guides(content: ContentBundle | None = None) -> tuple[str, ...]:
    """The graduation set: guides declared for the mortal stage."""

    try:
        definitions = _definitions(content)
    except FileNotFoundError:
        return INTRO_GUIDES
    keys = tuple(
        str(definition["key"])
        for definition in definitions
        if definition["stage"] == STAGE_MORTAL
    )
    return keys or INTRO_GUIDES


def intro_complete(flags: Iterable[str], content: ContentBundle | None = None) -> bool:
    """Return whether the mortal onboarding is finished.

    Only mortal-tier guides count, so finishing a realm-gated guide can never
    promote a player past onboarding.
    """

    completed = set(flags)
    return all(key in completed for key in mortal_guides(content))


def resolve_guide(value: str, content: ContentBundle | None = None) -> str | None:
    normalized = value.strip()
    if not normalized:
        return None
    return guide_alias_map(content).get(normalized)


def resolve_service(value: str) -> str | None:
    return SERVICE_ALIASES.get(value.strip())


def resolve_destination(value: str) -> str | None:
    return TRAVEL_DESTINATIONS.get(value.strip())


def validate_service(value: str) -> str:
    if value not in SERVICE_LABELS:
        raise ValueError("unsupported teaching service")
    return value


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"guide {field} must be a non-empty string")
    return value.strip()


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


def _definitions(content: ContentBundle | None) -> list[dict[str, Any]]:
    bundle = _bundle(content)
    definitions: list[dict[str, Any]] = []
    selectors: dict[str, str] = {}
    for row in bundle.list(KIND, include_locked=False):
        key = _string(row.get("key"), "key")
        name = _string(row.get("name"), f"{key}.name")
        label = row.get("label")
        label = name if label is None else _string(label, f"{key}.label")
        command = row.get("command")
        command = key if command is None else _string(command, f"{key}.command")
        raw_aliases = row.get("aliases", [])
        if not isinstance(raw_aliases, list):
            raise ContentError(f"guide {key} aliases must be a list")
        aliases = tuple(_string(alias, f"{key}.aliases") for alias in raw_aliases)
        for selector in (key, command, *aliases):
            owner = selectors.get(selector)
            if owner is not None and owner != key:
                raise ContentError(
                    f"guide selector {selector!r} is ambiguous between {owner} and {key}"
                )
            selectors[selector] = key

        stages, locations = _requirements(row.get("requirements"), bundle, key)
        output = row.get("output")
        if not isinstance(output, dict):
            raise ContentError(f"guide {key} output must be an object")
        item_key = output.get("item_key")
        quantity_range: tuple[int, int] | None = None
        raw_type = output.get("type")
        if raw_type is None:
            # A reward-only output omits the type; flags and teaching unlocks
            # must name their kind so the runtime knows what to record.
            output_type = "item_reward" if item_key is not None else ""
        else:
            output_type = _string(raw_type, f"{key}.output.type")
        if item_key is not None:
            item_key = _string(item_key, f"{key}.output.item_key")
            if not bundle.has("item", item_key, include_locked=False):
                raise ContentError(f"guide {key} rewards unknown item {item_key}")
            raw_range = output.get("quantity_range", [1, 1])
            if (
                not isinstance(raw_range, list)
                or len(raw_range) != 2
                or any(
                    isinstance(value, bool) or not isinstance(value, int) or value <= 0
                    for value in raw_range
                )
                or raw_range[0] > raw_range[1]
            ):
                raise ContentError(f"guide {key} output quantity_range is invalid")
            quantity_range = (int(raw_range[0]), int(raw_range[1]))
        elif output_type in {"intro_flag", "teaching_unlock"}:
            _string(output.get("key"), f"{key}.output.key")
        else:
            raise ContentError(f"guide {key} output needs a reward or flag")

        cost, refund = _cost(row.get("cost"), row.get("failure_refund"), key)
        options = row.get("options") or []
        if not isinstance(options, list) or any(
            not isinstance(option, str) or option not in SERVICE_LABELS for option in options
        ):
            raise ContentError(f"guide {key} options must name known services")

        definitions.append(
            {
                "key": key,
                "name": name,
                "label": label,
                "desc": _string(row.get("desc"), f"{key}.desc"),
                "command": command,
                "aliases": aliases,
                "stage": stages,
                "locations": locations,
                "output_type": output_type,
                "output": dict(output),
                "item_key": item_key,
                "quantity_range": quantity_range,
                "cost": cost,
                "failure_refund": refund,
                "options": tuple(options),
                "repeatable": bool(row.get("repeatable", False)),
                "preview_does_not_consume": bool(row.get("preview_does_not_consume", False)),
                "random_pool": row.get("random_pool"),
            }
        )
    if not definitions:
        raise ContentError("no active guides are registered")
    return definitions


def _requirements(
    value: Any, bundle: ContentBundle, key: str
) -> tuple[str, tuple[str, ...]]:
    if not isinstance(value, list) or not value:
        raise ContentError(f"guide {key} requirements must be a non-empty list")
    stages: list[str] = []
    locations: list[str] = []
    for requirement in value:
        if not isinstance(requirement, dict):
            raise ContentError(f"guide {key} has a malformed requirement")
        kind = requirement.get("type")
        if kind == "stage":
            if set(requirement) != {"type", "stage"}:
                raise ContentError(f"guide {key} stage requirement has unsupported fields")
            stage = _string(requirement.get("stage"), f"{key}.requirements.stage")
            if stage not in _SUPPORTED_STAGES:
                raise ContentError(f"guide {key} has unsupported stage {stage!r}")
            stages.append(stage)
        elif kind == "location":
            if set(requirement) != {"type", "location_key"}:
                raise ContentError(f"guide {key} location requirement has unsupported fields")
            location = _string(requirement.get("location_key"), f"{key}.requirements.location_key")
            if not bundle.has("location", location, include_locked=True):
                raise ContentError(f"guide {key} references unknown location {location}")
            locations.append(location)
        else:
            raise ContentError(f"guide {key} has unsupported requirement type {kind!r}")
    if len(stages) != 1:
        raise ContentError(f"guide {key} must declare exactly one stage requirement")
    return stages[0], tuple(locations)


def _cost(value: Any, refund_value: Any, key: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if value is None:
        cost: dict[str, Any] = {}
    elif not isinstance(value, dict):
        raise ContentError(f"guide {key} cost must be an object")
    else:
        cost = dict(value)
    if cost:
        resource = _string(cost.get("resource_key"), f"{key}.cost.resource_key")
        if resource not in {"stamina", "energy"}:
            raise ContentError(f"guide {key} cost resource must be stamina or energy")
        amount = cost.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ContentError(f"guide {key} cost amount must be a positive integer")
    refund: dict[str, Any] = dict(refund_value) if isinstance(refund_value, dict) else {}
    if refund:
        if not cost:
            raise ContentError(f"guide {key} declares a refund without a cost")
        if _string(refund.get("resource_key"), f"{key}.failure_refund.resource_key") != cost.get(
            "resource_key"
        ):
            raise ContentError(f"guide {key} refund resource must match its cost")
        refund_amount = refund.get("amount")
        if (
            isinstance(refund_amount, bool)
            or not isinstance(refund_amount, int)
            or refund_amount <= 0
            or refund_amount > int(cost["amount"])
        ):
            raise ContentError(f"guide {key} refund must not exceed its cost")
    return cost, refund


__all__ = [
    "GUIDE_CHOOSE_SERVICE",
    "GUIDE_GATHER_BLOOD_GRASS",
    "GUIDE_READ_WORLD",
    "INTRO_GUIDES",
    "KIND",
    "SERVICE_ALIASES",
    "SERVICE_LABELS",
    "STAGE_CULTIVATOR",
    "STAGE_MORTAL",
    "STAGE_NEW_USER",
    "STAGE_SEEKER",
    "TRAVEL_COSTS",
    "TRAVEL_DESTINATIONS",
    "TRAVEL_LABELS",
    "guide_alias_map",
    "guide_commands",
    "guide_definition",
    "guide_definitions",
    "guide_labels",
    "guides_for_stage",
    "intro_complete",
    "mortal_guides",
    "resolve_destination",
    "resolve_guide",
    "resolve_service",
    "validate_service",
]
