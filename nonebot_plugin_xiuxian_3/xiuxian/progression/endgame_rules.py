"""Pure rules for 合道、渡劫试炼 and terminal state transitions."""

from __future__ import annotations


from dataclasses import dataclass
from hashlib import blake2b
from typing import Any, Mapping

from ..content import ContentBundle, ContentError, bundled_content


ENDING_KEYS = frozenset({"ascend", "remain_in_world"})
PUBLIC_ENDING_CODEX_KEYS = {
    "ascend": "codex.ending.public_ascend",
    "remain_in_world": "codex.ending.public_remain",
}
ASCENSION_READY_STATUS = "ascension_ready"
ASCENDED_STATUS = "ascended"
REMAINED_IN_WORLD_STATUS = "remained_in_world"
ASCENSION_CERTIFICATE_KEY = "item.ascension_certificate"
FINAL_BATTLE_MIN_PROGRESS = 1_000
FINAL_BATTLE_MIN_MERIT = 1_000
DAO_UNION_TOTAL_CULTIVATION = 2_998_960
TRIBULATION_TOTAL_CULTIVATION = 8_998_960
DAO_UNION_FRAGMENT_COST = 10
DAO_UNION_MERIT_COST = 2_000
DAO_UNION_STONE_COST = 300_000
FINAL_BATTLE_MAX_MEMBERS = 5
FINAL_BATTLE_MAX_TURNS = 30
FINAL_BATTLE_LOBBY_SECONDS = 30 * 60
FINAL_BATTLE_COOLDOWN_SECONDS = 7 * 24 * 60 * 60
FINAL_BATTLE_ENEMY_KEY = "enemy.ascension_guardian"
FINAL_BATTLE_ENEMY_MAX_HP = 220_000
FINAL_BATTLE_ENEMY_ATTACK = 7_000
FINAL_BATTLE_ENEMY_INITIATIVE = 2_000
FINAL_BATTLE_ENEMY_AGILITY = 800
FINAL_BATTLE_ASSIST_MERIT_PER_DAMAGE = 1_000
FINAL_BATTLE_ASSIST_MERIT_CAP = 100
THREE_REALM_KEYS = ("xuantian", "demon", "beast")


def public_ending_codex_key(ending_key: str) -> str:
    try:
        return PUBLIC_ENDING_CODEX_KEYS[ending_key]
    except KeyError as exc:
        raise ValueError(f"unsupported ending key: {ending_key}") from exc


@dataclass(frozen=True, slots=True)
class TrialDefinition:
    key: str
    name: str
    description: str
    required_layer: int
    token_cost: int
    progress_reward: int
    merit_reward: int
    world_merit_reward: int
    debt_delta: int
    cooldown_seconds: int
    random_pool: str
    reward_items: dict[str, int]
    choice_minimum_progress: int | None
    choice_match_path_fruit: bool
    duration_seconds: int

    def snapshot(self) -> dict[str, Any]:
        choice = None
        if self.choice_minimum_progress is not None:
            choice = {
                "minimum_progress": self.choice_minimum_progress,
                "match_path_fruit": self.choice_match_path_fruit,
            }
        return {
            "key": self.key,
            "name": self.name,
            "desc": self.description,
            "required_layer": self.required_layer,
            "token_cost": self.token_cost,
            "progress_reward": self.progress_reward,
            "merit_reward": self.merit_reward,
            "world_merit_reward": self.world_merit_reward,
            "debt_delta": self.debt_delta,
            "cooldown_seconds": self.cooldown_seconds,
            "random_pool": self.random_pool,
            "reward_items": dict(self.reward_items),
            "choice": choice,
            "duration_seconds": self.duration_seconds,
        }


@dataclass(frozen=True, slots=True)
class TribulationDefinition:
    key: str
    name: str
    description: str
    required_realm_key: str
    required_layer: int
    duration_seconds: int
    trial_order: tuple[str, ...]
    trials: tuple[TrialDefinition, ...]


def tribulation_definition(content: ContentBundle | None = None) -> TribulationDefinition:
    bundle = content or bundled_content()
    event_key = "event.heaven_tribulation"
    try:
        event = bundle.require("event", event_key, include_locked=False)
        expected = {
            "name", "desc", "status", "requirements", "trial_order",
            "duration_seconds", "trials", "key",
        }
        if set(event) != expected:
            raise ContentError(f"{event_key} fields are invalid")
        name = _text(event["name"], f"{event_key}.name")
        description = _text(event["desc"], f"{event_key}.desc")
        requirements = event["requirements"]
        if (
            not isinstance(requirements, list)
            or len(requirements) != 1
            or not isinstance(requirements[0], dict)
            or set(requirements[0]) != {"type", "realm_key", "min_layer"}
            or requirements[0]["type"] != "realm"
        ):
            raise ContentError(f"{event_key}.requirements is invalid")
        required_realm_key = _text(requirements[0]["realm_key"], f"{event_key}.requirements.realm_key")
        bundle.require("realm", required_realm_key, include_locked=False)
        required_layer = _positive_int(requirements[0]["min_layer"], f"{event_key}.requirements.min_layer")
        duration_seconds = _positive_int(event["duration_seconds"], f"{event_key}.duration_seconds")
        order = event["trial_order"]
        if (
            not isinstance(order, list)
            or not order
            or any(not isinstance(value, str) or not value for value in order)
            or len(set(order)) != len(order)
        ):
            raise ContentError(f"{event_key}.trial_order is invalid")
        raw_trials = event["trials"]
        if not isinstance(raw_trials, list) or len(raw_trials) != len(order):
            raise ContentError(f"{event_key}.trials must match trial_order")
        trials = tuple(
            _trial_definition(raw, event_key, duration_seconds, bundle)
            for raw in raw_trials
        )
        if tuple(trial.key for trial in trials) != tuple(order):
            raise ContentError(f"{event_key}.trials must follow trial_order")
        if len({trial.name for trial in trials}) != len(trials):
            raise ContentError(f"{event_key}.trials contains duplicate names")
        return TribulationDefinition(
            key=event_key,
            name=name,
            description=description,
            required_realm_key=required_realm_key,
            required_layer=required_layer,
            duration_seconds=duration_seconds,
            trial_order=tuple(order),
            trials=trials,
        )
    except KeyError as exc:
        raise ContentError(f"{event_key} content is incomplete: {exc}") from exc


def trial_definition(trial_key: str, content: ContentBundle | None = None) -> TrialDefinition:
    definition = tribulation_definition(content)
    for trial in definition.trials:
        if trial.key == trial_key:
            return trial
    raise ContentError(f"unknown tribulation trial: {trial_key}")


def trial_definition_from_snapshot(
    value: Any,
    content: ContentBundle | None = None,
) -> TrialDefinition:
    return _trial_definition(value, "tribulation snapshot", None, content, allow_locked_refs=True)


def resolve_trial_key(value: str, content: ContentBundle | None = None) -> str | None:
    candidate = value.strip()
    definition = tribulation_definition(content)
    for trial in definition.trials:
        if candidate in {trial.key, trial.name}:
            return trial.key
    return None


def fruit_for_path(path_key: str | None, content: ContentBundle | None = None) -> str | None:
    if not path_key:
        return None
    bundle = content or bundled_content()
    row = bundle.get("path", str(path_key), include_locked=False)
    fruit_key = row.get("fruit_key") if row else None
    return fruit_key if isinstance(fruit_key, str) and fruit_key else None


def _trial_definition(
    raw: Any,
    event_key: str,
    duration_seconds: int | None,
    bundle: ContentBundle | None,
    *,
    allow_locked_refs: bool = False,
) -> TrialDefinition:
    if not isinstance(raw, dict):
        raise ContentError(f"{event_key}.trials contains a non-object")
    expected = {
        "key", "name", "desc", "required_layer", "token_cost", "progress_reward",
        "merit_reward", "world_merit_reward", "debt_delta", "cooldown_seconds",
        "random_pool", "reward_items", "choice",
    }
    snapshot_expected = expected | {"duration_seconds"}
    if set(raw) not in (expected, snapshot_expected):
        raise ContentError(f"{event_key}.trial fields are invalid")
    key = _text(raw["key"], f"{event_key}.trial.key")
    name = _text(raw["name"], f"{event_key}.{key}.name")
    description = _text(raw["desc"], f"{event_key}.{key}.desc")
    required_layer = _positive_int(raw["required_layer"], f"{event_key}.{key}.required_layer")
    token_cost = _positive_int(raw["token_cost"], f"{event_key}.{key}.token_cost")
    progress_reward = _non_negative_int(raw["progress_reward"], f"{event_key}.{key}.progress_reward")
    merit_reward = _non_negative_int(raw["merit_reward"], f"{event_key}.{key}.merit_reward")
    world_merit_reward = _non_negative_int(raw["world_merit_reward"], f"{event_key}.{key}.world_merit_reward")
    debt_delta = _non_negative_int(raw["debt_delta"], f"{event_key}.{key}.debt_delta")
    cooldown_seconds = _positive_int(raw["cooldown_seconds"], f"{event_key}.{key}.cooldown_seconds")
    random_pool = _text(raw["random_pool"], f"{event_key}.{key}.random_pool")
    if not random_pool.startswith("battle.enemy."):
        raise ContentError(f"{event_key}.{key}.random_pool must reference a battle enemy")
    if bundle is not None:
        bundle.require(
            "enemy",
            random_pool.removeprefix("battle."),
            include_locked=allow_locked_refs,
        )
    raw_rewards = raw["reward_items"]
    if not isinstance(raw_rewards, Mapping):
        raise ContentError(f"{event_key}.{key}.reward_items is invalid")
    reward_items: dict[str, int] = {}
    for item_key, quantity in raw_rewards.items():
        item_key = _text(item_key, f"{event_key}.{key}.reward_items.key")
        if not item_key.startswith("item."):
            raise ContentError(f"{event_key}.{key}.reward_items contains a non-item key")
        if bundle is not None:
            try:
                bundle.require("item", item_key, include_locked=allow_locked_refs)
            except KeyError as exc:
                raise ContentError(
                    f"{event_key}.{key}.reward_items references unknown item: {item_key}"
                ) from exc
        reward_items[item_key] = _positive_int(quantity, f"{event_key}.{key}.reward_items.{item_key}")
    choice = raw["choice"]
    choice_minimum_progress: int | None
    choice_match_path_fruit: bool
    if choice is None:
        choice_minimum_progress = None
        choice_match_path_fruit = False
    else:
        if not isinstance(choice, dict) or set(choice) != {"minimum_progress", "match_path_fruit"}:
            raise ContentError(f"{event_key}.{key}.choice is invalid")
        choice_minimum_progress = _positive_int(choice["minimum_progress"], f"{event_key}.{key}.choice.minimum_progress")
        if not isinstance(choice["match_path_fruit"], bool):
            raise ContentError(f"{event_key}.{key}.choice.match_path_fruit is invalid")
        choice_match_path_fruit = choice["match_path_fruit"]
    configured_duration = raw.get("duration_seconds", duration_seconds)
    if configured_duration is None:
        raise ContentError(f"{event_key}.{key}.duration_seconds is missing")
    configured_duration = _positive_int(configured_duration, f"{event_key}.{key}.duration_seconds")
    if duration_seconds is not None and configured_duration != duration_seconds:
        raise ContentError(f"{event_key}.{key}.duration_seconds differs from event duration")
    return TrialDefinition(
        key=key,
        name=name,
        description=description,
        required_layer=required_layer,
        token_cost=token_cost,
        progress_reward=progress_reward,
        merit_reward=merit_reward,
        world_merit_reward=world_merit_reward,
        debt_delta=debt_delta,
        cooldown_seconds=cooldown_seconds,
        random_pool=random_pool,
        reward_items=reward_items,
        choice_minimum_progress=choice_minimum_progress,
        choice_match_path_fruit=choice_match_path_fruit,
        duration_seconds=configured_duration,
    )


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"{field} must be a non-empty string")
    return value.strip()


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"{field} must be a positive integer")
    return value


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContentError(f"{field} must be a non-negative integer")
    return value


def trial_roll_bp(operation_id: str) -> int:
    return int.from_bytes(blake2b(operation_id.encode("utf-8"), digest_size=2).digest(), "big") % 10_000


def trial_success(trial_key: str, roll_bp: int) -> bool:
    # The battle engine remains locked; this deterministic gate is only the
    # replayable contract fixture for the progression state machine.
    return int(roll_bp) < 7_000


__all__ = [
    "ASCENDED_STATUS",
    "ASCENSION_READY_STATUS",
    "ASCENSION_CERTIFICATE_KEY",
    "DAO_UNION_TOTAL_CULTIVATION",
    "TRIBULATION_TOTAL_CULTIVATION",
    "DAO_UNION_FRAGMENT_COST",
    "DAO_UNION_MERIT_COST",
    "DAO_UNION_STONE_COST",
    "THREE_REALM_KEYS",
    "ENDING_KEYS",
    "FINAL_BATTLE_ASSIST_MERIT_CAP",
    "FINAL_BATTLE_ASSIST_MERIT_PER_DAMAGE",
    "FINAL_BATTLE_COOLDOWN_SECONDS",
    "FINAL_BATTLE_ENEMY_AGILITY",
    "FINAL_BATTLE_ENEMY_ATTACK",
    "FINAL_BATTLE_ENEMY_INITIATIVE",
    "FINAL_BATTLE_ENEMY_KEY",
    "FINAL_BATTLE_ENEMY_MAX_HP",
    "FINAL_BATTLE_LOBBY_SECONDS",
    "FINAL_BATTLE_MAX_MEMBERS",
    "FINAL_BATTLE_MAX_TURNS",
    "FINAL_BATTLE_MIN_MERIT",
    "FINAL_BATTLE_MIN_PROGRESS",
    "REMAINED_IN_WORLD_STATUS",
    "TrialDefinition",
    "TribulationDefinition",
    "tribulation_definition",
    "trial_definition",
    "trial_definition_from_snapshot",
    "resolve_trial_key",
    "trial_roll_bp",
    "trial_success",
    "fruit_for_path",
]
