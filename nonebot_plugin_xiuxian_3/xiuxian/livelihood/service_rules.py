"""Content-backed rules for player-to-player livelihood services."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content


SERVICE_GATHER_HELP = "service.gather_help"
SERVICE_COOK_MEAL = "service.cook_meal"


@dataclass(frozen=True, slots=True)
class ServiceDefinition:
    key: str
    label: str
    description: str
    aliases: tuple[str, ...]
    daily_limit: int
    default_reward_stones: int
    fixed_reward: bool
    minimum_reward_stones: int
    maximum_reward_stones: int
    required_service_reputation: int = 0
    required_teaching_flag: str | None = None
    required_teaching_service: str | None = None
    provider_stamina: int = 0
    provider_energy: int = 0
    provider_inputs: dict[str, int] | None = None
    publisher_outputs: dict[str, int] | None = None
    failure_provider_refund: dict[str, int] | None = None
    failure_stamina_refund: int = 0
    duration_seconds: int = 24 * 60 * 60
    requires_same_location: bool = True


def _integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContentError(f"service {field} must be an integer >= {minimum}")
    return value


def _asset_map(
    value: Any,
    *,
    field: str,
    content: ContentBundle,
) -> dict[str, int]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ContentError(f"service {field} must be an object")
    result: dict[str, int] = {}
    for raw_key, raw_amount in value.items():
        key = str(raw_key)
        if not key.startswith("item.") or not content.has("item", key, include_locked=False):
            raise ContentError(f"service {field} references unknown item {key!r}")
        result[key] = _integer(raw_amount, f"{field}.{key}", minimum=1)
    return result


def _input_map(value: Any, *, content: ContentBundle, key: str) -> dict[str, int]:
    if value is None:
        return {}
    if not isinstance(value, list):
        raise ContentError(f"service {key} cost.inputs must be a list")
    result: dict[str, int] = {}
    for item in value:
        if not isinstance(item, dict):
            raise ContentError(f"service {key} has an invalid input")
        item_key = item.get("item_key")
        if (
            not isinstance(item_key, str)
            or not item_key.startswith("item.")
            or not content.has("item", item_key, include_locked=False)
        ):
            raise ContentError(f"service {key} references unknown input item")
        quantity = _integer(item.get("quantity"), f"{key} cost.inputs.quantity", minimum=1)
        if item_key in result:
            raise ContentError(f"service {key} repeats input item {item_key!r}")
        result[item_key] = quantity
    return result


def _service_definition(row: dict[str, Any], content: ContentBundle) -> ServiceDefinition:
    key = row.get("key")
    label = row.get("name")
    if not isinstance(key, str) or not key or not isinstance(label, str) or not label.strip():
        raise ContentError("service requires a key and name")
    description = row.get("desc")
    if not isinstance(description, str) or not description.strip():
        raise ContentError(f"service {key} requires a description")
    aliases = row.get("aliases", [])
    if not isinstance(aliases, list) or any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
        raise ContentError(f"service {key} aliases must be non-empty strings")
    requirements = row.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        raise ContentError(f"service {key} requirements must be a non-empty list")
    service_reputation = 0
    teaching_flag: str | None = None
    teaching_service: str | None = None
    for requirement in requirements:
        if not isinstance(requirement, dict):
            raise ContentError(f"service {key} has an invalid requirement")
        requirement_type = requirement.get("type")
        if requirement_type == "service_reputation":
            if set(requirement) != {"type", "min"}:
                raise ContentError(f"service {key} has an invalid service reputation requirement")
            if service_reputation:
                raise ContentError(f"service {key} repeats service reputation requirement")
            service_reputation = _integer(requirement.get("min"), f"{key} service reputation", minimum=1)
        elif requirement_type == "teaching":
            if set(requirement) not in ({"type", "key"}, {"type", "key", "service"}):
                raise ContentError(f"service {key} has an invalid teaching requirement")
            if teaching_flag is not None:
                raise ContentError(f"service {key} repeats teaching requirement")
            teaching_flag = requirement.get("key")
            if not isinstance(teaching_flag, str) or not teaching_flag:
                raise ContentError(f"service {key} teaching requirement has no key")
            if not content.has("guide", teaching_flag, include_locked=False):
                raise ContentError(f"service {key} references unknown teaching guide {teaching_flag!r}")
            teaching_service = requirement.get("service")
            if teaching_service is not None and (
                not isinstance(teaching_service, str) or not teaching_service
            ):
                raise ContentError(f"service {key} teaching requirement has invalid service")
        else:
            raise ContentError(f"service {key} has unsupported requirement {requirement_type!r}")

    cost = row.get("cost")
    if not isinstance(cost, dict):
        raise ContentError(f"service {key} cost must be an object")
    stamina = _integer(cost.get("stamina", 0), f"{key} stamina cost")
    energy = _integer(cost.get("energy", 0), f"{key} energy cost")
    inputs = _input_map(cost.get("inputs"), content=content, key=key)
    if not stamina and not energy and not inputs:
        raise ContentError(f"service {key} must have a provider cost")

    reward = row.get("reward")
    if not isinstance(reward, dict) or reward.get("currency_key") != "currency.spirit_stone":
        raise ContentError(f"service {key} must reward spirit stones")
    has_fixed_amount = "amount" in reward
    has_range = {"default_amount", "min_amount", "max_amount"}.issubset(reward)
    if has_fixed_amount == has_range:
        raise ContentError(f"service {key} must declare either amount or a reward range")
    if has_fixed_amount:
        amount = _integer(reward.get("amount"), f"{key} reward amount", minimum=1)
        minimum = maximum = amount
    else:
        amount = _integer(reward.get("default_amount"), f"{key} default reward", minimum=1)
        minimum = _integer(reward.get("min_amount"), f"{key} minimum reward", minimum=1)
        maximum = _integer(reward.get("max_amount"), f"{key} maximum reward", minimum=minimum)
        if amount < minimum or amount > maximum:
            raise ContentError(f"service {key} default reward is outside its range")

    failure_provider_refund = _asset_map(
        row.get("failure_provider_refund"), field=f"{key} failure_provider_refund", content=content
    )
    for item_key, refund_amount in failure_provider_refund.items():
        if refund_amount > inputs.get(item_key, 0):
            raise ContentError(f"service {key} refunds more input than it costs")
    failure_stamina_refund = _integer(
        row.get("failure_stamina_refund", 0), f"{key} failure stamina refund"
    )
    if failure_stamina_refund > stamina:
        raise ContentError(f"service {key} refunds more stamina than it costs")
    daily_limit = _integer(row.get("daily_limit"), f"{key} daily limit", minimum=1)
    duration = _integer(row.get("duration_seconds", 24 * 60 * 60), f"{key} duration", minimum=1)
    same_location = row.get("requires_same_location")
    if not isinstance(same_location, bool):
        raise ContentError(f"service {key} requires_same_location must be boolean")
    return ServiceDefinition(
        key=key,
        label=label.strip(),
        description=description.strip(),
        aliases=tuple(alias.strip() for alias in aliases),
        daily_limit=daily_limit,
        default_reward_stones=amount,
        fixed_reward=has_fixed_amount,
        minimum_reward_stones=minimum,
        maximum_reward_stones=maximum,
        required_service_reputation=service_reputation,
        required_teaching_flag=teaching_flag,
        required_teaching_service=teaching_service,
        provider_stamina=stamina,
        provider_energy=energy,
        provider_inputs=inputs or None,
        publisher_outputs=_asset_map(
            row.get("publisher_outputs"), field=f"{key} publisher_outputs", content=content
        ) or None,
        failure_provider_refund=failure_provider_refund or None,
        failure_stamina_refund=failure_stamina_refund,
        duration_seconds=duration,
        requires_same_location=same_location,
    )


@lru_cache(maxsize=1)
def _bundled_service_definitions() -> dict[str, ServiceDefinition]:
    return service_definitions(bundled_content())


def service_definitions(content: ContentBundle | None = None) -> dict[str, ServiceDefinition]:
    bundle = content if content is not None else bundled_content()
    result: dict[str, ServiceDefinition] = {}
    selectors: set[str] = set()
    for row in bundle.list("livelihood", include_locked=False):
        if row.get("record_type") != "service":
            continue
        definition = _service_definition(row, bundle)
        selectors_for_row = {definition.key, definition.label, *definition.aliases}
        if selectors & selectors_for_row:
            raise ContentError(f"service {definition.key} has a duplicate name or alias")
        selectors.update(selectors_for_row)
        result[definition.key] = definition
    if not result:
        raise ContentError("no active service definitions found")
    return result


def service_definition(
    value: str | None = None,
    content: ContentBundle | None = None,
) -> ServiceDefinition:
    definitions = service_definitions(content) if content is not None else _bundled_service_definitions()
    normalized = (value or "").strip()
    for definition in definitions.values():
        if normalized in {definition.key, definition.label, *definition.aliases}:
            return definition
    raise ValueError(f"unsupported service key: {value}")


def service_reward(definition: ServiceDefinition, requested: int | None = None) -> int:
    reward = definition.default_reward_stones if requested is None else requested
    if isinstance(reward, bool) or not isinstance(reward, int):
        raise ValueError("service reward must be an integer")
    if definition.fixed_reward and reward != definition.default_reward_stones:
        raise ValueError("service reward is fixed")
    if reward < definition.minimum_reward_stones or reward > definition.maximum_reward_stones:
        raise ValueError("service reward is outside the allowed range")
    return reward


__all__ = [
    "SERVICE_COOK_MEAL",
    "SERVICE_GATHER_HELP",
    "ServiceDefinition",
    "service_definition",
    "service_definitions",
    "service_reward",
]
