"""Pure v0.6 rules for 合道、渡劫试炼 and terminal state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import blake2b


CONTENT_VERSION = "content-0.6"
RULE_VERSION = "progression-0.6.0"
ENDING_KEYS = frozenset({"ascend", "remain_in_world"})
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
TRIBULATION_TRIAL_DURATION_SECONDS = 30 * 60
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
TRIBULATION_COOLDOWN_SECONDS = {
    "trial.body_and_mind": 24 * 60 * 60,
    "trial.three_realms": 48 * 60 * 60,
    "trial.dao_choice": 72 * 60 * 60,
}
TRIBULATION_DEBT_DELTA = {
    "trial.body_and_mind": 10,
    "trial.three_realms": 15,
    "trial.dao_choice": 20,
}
TRIBULATION_PROGRESS_REWARD = {
    "trial.body_and_mind": 100,
    "trial.three_realms": 180,
    "trial.dao_choice": 250,
}
TRIBULATION_MERIT_REWARD = {
    # Keep the resource closure explicit: the three trials contribute 550,
    # while the three dao-origin tasks contribute the remaining 450.
    "trial.body_and_mind": 100,
    "trial.three_realms": 200,
    "trial.dao_choice": 250,
}
TRIBULATION_WORLD_MERIT_REWARD = {
    "trial.body_and_mind": 0,
    "trial.three_realms": 500,
    "trial.dao_choice": 0,
}
TRIAL_ORDER = ("trial.body_and_mind", "trial.three_realms", "trial.dao_choice")
THREE_REALM_KEYS = ("xuantian", "demon", "beast")
TRIAL_LABELS = {
    "trial.body_and_mind": "身心劫",
    "trial.three_realms": "三界劫",
    "trial.dao_choice": "道果劫",
}
FRUIT_BY_PATH = {
    "body": "fruit.immortal_body",
    "spell": "fruit.origin_spell",
    "device": "fruit.machine_heaven",
    "demonic": "fruit.free_demon",
    "beast": "fruit.ancestral_king",
    "support": "fruit.allcraft",
}
FRUIT_KEYS = frozenset(FRUIT_BY_PATH.values())


@dataclass(frozen=True, slots=True)
class TrialDefinition:
    key: str
    required_layer: int
    token_cost: int
    progress_reward: int
    merit_reward: int
    debt_delta: int
    cooldown_seconds: int
    random_pool: str


TRIAL_DEFINITIONS = {
    key: TrialDefinition(
        key=key,
        required_layer=3 if key == "trial.body_and_mind" else 6 if key == "trial.three_realms" else 9,
        token_cost=1,
        progress_reward=TRIBULATION_PROGRESS_REWARD[key],
        merit_reward=TRIBULATION_MERIT_REWARD[key],
        debt_delta=TRIBULATION_DEBT_DELTA[key],
        cooldown_seconds=TRIBULATION_COOLDOWN_SECONDS[key],
        random_pool=f"tribulation.{key}.v0.6",
    )
    for key in TRIAL_ORDER
}


def trial_definition(trial_key: str) -> TrialDefinition:
    return TRIAL_DEFINITIONS[trial_key]


def trial_roll_bp(operation_id: str) -> int:
    return int.from_bytes(blake2b(operation_id.encode("utf-8"), digest_size=2).digest(), "big") % 10_000


def trial_success(trial_key: str, roll_bp: int) -> bool:
    # The battle engine remains locked; this deterministic gate is only the
    # replayable contract fixture for the progression state machine.
    return int(roll_bp) < 7_000


def fruit_for_path(path_key: str | None) -> str | None:
    return FRUIT_BY_PATH.get(str(path_key or ""))


__all__ = [
    "ASCENDED_STATUS",
    "ASCENSION_READY_STATUS",
    "ASCENSION_CERTIFICATE_KEY",
    "CONTENT_VERSION",
    "RULE_VERSION",
    "DAO_UNION_TOTAL_CULTIVATION",
    "TRIBULATION_TOTAL_CULTIVATION",
    "DAO_UNION_FRAGMENT_COST",
    "DAO_UNION_MERIT_COST",
    "DAO_UNION_STONE_COST",
    "TRIBULATION_TRIAL_DURATION_SECONDS",
    "TRIBULATION_WORLD_MERIT_REWARD",
    "TRIAL_ORDER",
    "TRIAL_LABELS",
    "THREE_REALM_KEYS",
    "FRUIT_KEYS",
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
    "trial_definition",
    "trial_roll_bp",
    "trial_success",
    "fruit_for_path",
]
