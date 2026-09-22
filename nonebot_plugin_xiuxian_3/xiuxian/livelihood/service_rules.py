"""Pure rules for the first player-to-player livelihood service orders."""

from __future__ import annotations

from dataclasses import dataclass

from .rules import CONTENT_VERSION, RULE_VERSION


SERVICE_GATHER_HELP = "service.gather_help"
SERVICE_COOK_MEAL = "service.cook_meal"


@dataclass(frozen=True, slots=True)
class ServiceDefinition:
    key: str
    label: str
    daily_limit: int
    default_reward_stones: int
    fixed_reward: bool
    required_service_reputation: int = 0
    required_teaching: bool = False
    provider_stamina: int = 0
    provider_energy: int = 0
    provider_inputs: dict[str, int] | None = None
    publisher_outputs: dict[str, int] | None = None
    failure_provider_refund: dict[str, int] | None = None
    failure_stamina_refund: int = 0
    duration_seconds: int = 24 * 60 * 60
    content_version: str = CONTENT_VERSION
    rule_version: str = RULE_VERSION


SERVICE_DEFINITIONS = {
    SERVICE_GATHER_HELP: ServiceDefinition(
        key=SERVICE_GATHER_HELP,
        label="教学采集协助",
        daily_limit=3,
        default_reward_stones=15,
        fixed_reward=True,
        required_service_reputation=10,
        provider_stamina=3,
        publisher_outputs={"item.herb.blood_grass": 1},
        failure_stamina_refund=1,
    ),
    SERVICE_COOK_MEAL: ServiceDefinition(
        key=SERVICE_COOK_MEAL,
        label="烹饪服务",
        daily_limit=5,
        default_reward_stones=20,
        fixed_reward=False,
        required_teaching=True,
        provider_energy=2,
        provider_inputs={"item.food.coarse_spirit_rice": 2},
        publisher_outputs={"item.food.spirit_rice": 2},
        failure_provider_refund={"item.food.coarse_spirit_rice": 1},
    ),
}

SERVICE_ALIASES = {
    SERVICE_GATHER_HELP: SERVICE_GATHER_HELP,
    "教学采集协助": SERVICE_GATHER_HELP,
    "采集协助": SERVICE_GATHER_HELP,
    "service.gather_help": SERVICE_GATHER_HELP,
    SERVICE_COOK_MEAL: SERVICE_COOK_MEAL,
    "烹饪服务": SERVICE_COOK_MEAL,
    "烹饪": SERVICE_COOK_MEAL,
    "service.cook_meal": SERVICE_COOK_MEAL,
}


def service_definition(value: str | None = None) -> ServiceDefinition:
    key = SERVICE_ALIASES.get((value or "").strip(), (value or "").strip())
    try:
        return SERVICE_DEFINITIONS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported service key: {value}") from exc


def service_reward(definition: ServiceDefinition, requested: int | None = None) -> int:
    reward = definition.default_reward_stones if requested is None else requested
    if definition.fixed_reward and reward != definition.default_reward_stones:
        raise ValueError("service reward is fixed")
    if reward <= 0 or reward > 100:
        raise ValueError("service reward is outside the allowed range")
    return reward


__all__ = [
    "SERVICE_ALIASES",
    "SERVICE_COOK_MEAL",
    "SERVICE_DEFINITIONS",
    "SERVICE_GATHER_HELP",
    "ServiceDefinition",
    "service_definition",
    "service_reward",
]
