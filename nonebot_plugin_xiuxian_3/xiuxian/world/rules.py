"""Movement definitions for the first world slice."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ..content import ContentBundle, bundled_content


@dataclass(frozen=True, slots=True)
class DestinationDefinition:
    key: str
    label: str
    duration_seconds: int
    stamina_cost: int
    currency_cost: int
    required_realm: str | None = None
    required_layer: int = 0
    pass_key: str | None = None
    pass_quantity: int = 0
    required_dao_fruit_progress: int = 0
    daily_start_limit: int = 0
    required_endgame_status: str | None = None
    required_intro_flag: str | None = None
    consume_pass_on_arrival: bool = False
    required_faction: str | None = None
    required_faction_reputation: int = 0
    requires_selected_domain: bool = False
    requirements: tuple[dict[str, object], ...] = ()
    route_available: bool = True
    region_open: bool = True


@dataclass(frozen=True, slots=True)
class _RequirementSummary:
    required_realm: str | None
    required_layer: int
    required_dao_fruit_progress: int
    required_endgame_status: str | None
    required_intro_flag: str | None
    required_faction: str | None
    required_faction_reputation: int
    requires_selected_domain: bool


def _content_destination(destination: str, content: ContentBundle) -> DestinationDefinition | None:
    location = content.get("location", destination, include_locked=True)
    if location is None:
        return None
    raw_requirements = location.get("requirements") or []
    requirements = tuple(item for item in raw_requirements if isinstance(item, dict))
    summary = _requirement_summary(requirements)
    return DestinationDefinition(
        key=destination,
        label=str(location.get("name") or destination),
        duration_seconds=0,
        stamina_cost=0,
        currency_cost=0,
        required_realm=summary.required_realm,
        required_layer=summary.required_layer,
        required_dao_fruit_progress=summary.required_dao_fruit_progress,
        required_endgame_status=summary.required_endgame_status,
        required_intro_flag=summary.required_intro_flag,
        required_faction=summary.required_faction,
        required_faction_reputation=summary.required_faction_reputation,
        requires_selected_domain=summary.requires_selected_domain,
        requirements=requirements,
        route_available=False,
    )


def _content_destination_for_source(
    destination: str, source: str, content: ContentBundle
) -> DestinationDefinition | None:
    location = content.get("location", destination, include_locked=True)
    if location is None:
        return None
    selected: dict[str, object] | None = None
    region_open = False
    for region in content.list("world_region", include_locked=True):
        for connection in region.get("connections", []):
            if (
                isinstance(connection, dict)
                and connection.get("from") == source
                and connection.get("to") == destination
            ):
                selected = connection
                region_open = region.get("status") in {"active", "open"}
                break
        if selected is not None:
            break
    location_requirements = location.get("requirements") or []
    route_requirements = selected.get("requirements") or [] if selected is not None else []
    requirements = tuple(
        item
        for item in (
            *location_requirements,
            *route_requirements,
        )
        if isinstance(item, dict)
    )
    summary = _requirement_summary(requirements)
    return DestinationDefinition(
        key=destination,
        label=str(location.get("name") or destination),
        duration_seconds=int(selected.get("duration_seconds", 0)) if selected is not None else 0,
        stamina_cost=int(selected.get("stamina", 0)) if selected is not None else 0,
        currency_cost=int(selected.get("spirit_stone", 0)) if selected is not None else 0,
        required_realm=summary.required_realm,
        required_layer=summary.required_layer,
        pass_key=str(selected["item_key"]) if selected is not None and selected.get("item_key") is not None else None,
        pass_quantity=int(selected.get("item_quantity", 0)) if selected is not None else 0,
        required_dao_fruit_progress=summary.required_dao_fruit_progress,
        daily_start_limit=int(selected.get("daily_start_limit", 0)) if selected is not None else 0,
        required_endgame_status=summary.required_endgame_status,
        required_intro_flag=summary.required_intro_flag,
        consume_pass_on_arrival=(
            bool(selected.get("consume_pass_on_arrival", False)) if selected is not None else False
        ),
        required_faction=summary.required_faction,
        required_faction_reputation=summary.required_faction_reputation,
        requires_selected_domain=summary.requires_selected_domain,
        requirements=requirements,
        route_available=selected is not None,
        region_open=region_open,
    )


def _requirements_of(
    requirements: tuple[dict[str, object], ...], kind: str
) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for requirement in requirements:
        if requirement.get("type") == kind:
            found.append(requirement)
        conditions = requirement.get("conditions")
        if isinstance(conditions, list):
            found.extend(_requirements_of(tuple(item for item in conditions if isinstance(item, dict)), kind))
    return found


def _requirement_summary(requirements: tuple[dict[str, object], ...]) -> _RequirementSummary:
    realm_requirements = _requirements_of(requirements, "realm")
    required_realm = None
    required_layer = 0
    for requirement in realm_requirements:
        realm_key = requirement.get("realm_key")
        layer = requirement.get("min_layer")
        if isinstance(realm_key, str) and isinstance(layer, int):
            if required_realm is None or (realm_rank(realm_key), layer) > (realm_rank(required_realm), required_layer):
                required_realm, required_layer = realm_key, layer

    faction_requirements = _requirements_of(requirements, "faction_reputation")
    required_faction = str(faction_requirements[0]["faction"]) if faction_requirements else None
    required_faction_reputation = max(
        (
            int(item.get("minimum", item.get("min", 0)))
            for item in faction_requirements
            if item.get("faction") == required_faction
        ),
        default=0,
    )
    intro_requirements = _requirements_of(requirements, "intro_flag")
    endgame_requirements = _requirements_of(requirements, "endgame_status")
    dao_progress_requirements = _requirements_of(requirements, "dao_fruit_progress")
    return _RequirementSummary(
        required_realm=required_realm,
        required_layer=required_layer,
        required_dao_fruit_progress=max(
            (int(item.get("minimum", item.get("min", 0))) for item in dao_progress_requirements),
            default=0,
        ),
        required_endgame_status=str(endgame_requirements[0]["value"]) if endgame_requirements else None,
        required_intro_flag=str(intro_requirements[0]["value"]) if intro_requirements else None,
        required_faction=required_faction,
        required_faction_reputation=required_faction_reputation,
        requires_selected_domain=bool(_requirements_of(requirements, "selected_domain")),
    )


def resolve_destination(value: str, content: ContentBundle | None = None) -> str | None:
    normalized = value.strip()
    bundle = content or bundled_content()
    if bundle.has("location", normalized, include_locked=True):
        return normalized
    for location in bundle.list("location", include_locked=True):
        if normalized == location.get("name") or normalized in location.get("aliases", []):
            return str(location["key"])
    return None


def destination_definition(
    destination: str, content: ContentBundle | None = None, *, source: str | None = None
) -> DestinationDefinition:
    bundle = content or bundled_content()
    resolved = (
        _content_destination_for_source(destination, source, bundle)
        if source is not None
        else _content_destination(destination, bundle)
    )
    if resolved is None:
        raise ValueError(f"destination is not registered in content: {destination}")
    return resolved


def destination_location_is_open(destination: str, content: ContentBundle | None) -> bool:
    bundle = content or bundled_content()
    location = bundle.get("location", destination, include_locked=True)
    return location is not None and location.get("status") in {"active", "open"}


def unmet_travel_requirements(
    requirements: Iterable[dict[str, object]], state: Mapping[str, object]
) -> tuple[str, ...]:
    """Evaluate location and directional route requirements against one player snapshot."""

    realm_key = str(state.get("realm_key", "mortal"))
    realm_layer = int(state.get("realm_layer", 0))
    stage = str(state.get("stage", "new_user"))
    intro_flags = set(state.get("intro_flags", ()))
    inventory = state.get("inventory", {})
    faction_reputation = state.get("faction_reputation", {})
    completed_quests = set(state.get("completed_quests", ()))
    mentor_invitation = bool(state.get("mentor_invitation", False))
    endgame_status = str(state.get("endgame_status", "none"))
    domain_key = state.get("domain_key")
    dao_fruit_progress = int(state.get("dao_fruit_progress", 0))
    stage_ranks = {"new_user": 0, "mortal": 1, "seeker": 2, "cultivator": 3}

    def evaluate(requirement: dict[str, object]) -> tuple[str, ...]:
        kind = requirement.get("type")
        if kind == "any_of":
            branches = requirement.get("conditions", [])
            missing_branches = [evaluate(item) for item in branches if isinstance(item, dict)]
            if any(not branch for branch in missing_branches):
                return ()
            return ("或".join("、".join(branch) for branch in missing_branches),)
        if kind == "realm":
            needed = str(requirement["realm_key"])
            layer = int(requirement["min_layer"])
            return () if meets_realm(realm_key, realm_layer, needed, layer) else (f"境界要求（{needed} L{layer}）",)
        if kind == "item":
            key = str(requirement["item_key"])
            quantity = int(requirement["quantity"])
            amount = inventory.get(key, 0) if isinstance(inventory, Mapping) else 0
            return () if isinstance(amount, int) and not isinstance(amount, bool) and amount >= quantity else ("通行物品",)
        if kind == "quest_completed":
            key = str(requirement["quest_key"])
            return () if key in intro_flags or key in completed_quests else ("任务权限",)
        if kind == "mentor_invitation":
            return () if mentor_invitation else ("师门邀请",)
        if kind == "stage_min":
            required = str(requirement["stage"])
            return () if stage_ranks.get(stage, -1) >= stage_ranks.get(required, 10**6) else ("角色阶段",)
        if kind == "intro_flag":
            flag = str(requirement["value"])
            return () if flag in intro_flags or flag in completed_quests else ("任务权限",)
        if kind == "endgame_status":
            expected = str(requirement["value"])
            return () if endgame_status == expected else ("终局状态",)
        if kind == "faction_reputation":
            faction = str(requirement["faction"])
            minimum = int(requirement.get("minimum", requirement.get("min", 0)))
            current = faction_reputation.get(faction, 0) if isinstance(faction_reputation, Mapping) else 0
            label = {"demon": "魔界", "beast": "妖界"}.get(faction, faction)
            return () if isinstance(current, int) and not isinstance(current, bool) and current >= minimum else (f"{label}声望（需要 {minimum}，当前 {current}）",)
        if kind == "selected_domain":
            return () if isinstance(domain_key, str) and bool(domain_key) else ("已选择领域",)
        if kind == "dao_fruit_progress":
            minimum = int(requirement.get("minimum", requirement.get("min", 0)))
            return () if dao_fruit_progress >= minimum else ("道果进度",)
        raise ValueError(f"unsupported travel requirement: {kind!r}")

    missing: list[str] = []
    for requirement in requirements:
        missing.extend(evaluate(requirement))
    return tuple(dict.fromkeys(missing))


def realm_rank(realm_key: str) -> int:
    return {
        "mortal": 0,
        "qi_sensing": 1,
        "qi_gathering": 2,
        "foundation": 3,
        "golden_core": 4,
        "nascent_soul": 5,
        "soul_transformation": 6,
        "void_refining": 7,
        "dao_union": 8,
        "tribulation": 9,
    }.get(realm_key, -1)


def meets_realm(realm_key: str, layer: int, required_realm: str | None, required_layer: int) -> bool:
    if required_realm is None:
        return True
    return (realm_rank(realm_key), int(layer)) >= (realm_rank(required_realm), required_layer)
