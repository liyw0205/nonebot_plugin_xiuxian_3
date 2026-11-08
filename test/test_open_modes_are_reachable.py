"""The two repaired exploration modes must be reachable and payable.

`explore.cloud_city_escort` and `explore.spirit_field_tending` were declared
`open` but no location listed them, so a player standing in 云城 or 灵泉谷 could
never see or start them.  Listing the action is only half the contract: the
reward pool and the encounter pool the mode names must resolve too, and the mode
must stay publicly accessible.
"""

from __future__ import annotations

from pathlib import Path

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle

DATA = Path(__file__).parents[1] / "data"

REPAIRED_MODES = {
    "explore.cloud_city_escort": "xuantian.cloud_city",
    "explore.spirit_field_tending": "xuantian.spirit_field",
}


def test_repaired_modes_are_listed_and_their_pools_resolve() -> None:
    bundle = ContentBundle.load(DATA)
    problems: list[str] = []
    for mode_key, location_key in REPAIRED_MODES.items():
        mode = bundle.require("exploration_mode", mode_key)
        location = bundle.require("location", location_key)
        if mode.get("status") != "open":
            problems.append(f"{mode_key} is not open")
        if mode_key not in (location.get("actions") or []):
            problems.append(f"{location_key} does not list {mode_key}")
        if mode.get("location_key") != location_key:
            problems.append(f"{mode_key} belongs to {mode.get('location_key')}")
        for field in ("reward_pool_key", "enemy_pool_key"):
            pool_key = mode.get(field)
            if not isinstance(pool_key, str) or not bundle.has("reward", pool_key) and not bundle.has(
                "encounter_pool", pool_key
            ):
                problems.append(f"{mode_key} has no resolvable {field}")
        if mode.get("battle_chance_bp", 0) <= 0:
            problems.append(f"{mode_key} never rolls a battle")
        if mode.get("access_any"):
            problems.append(f"{mode_key} declares an unexpected access gate")
        if mode.get("required_realm") not in {row["key"] for row in bundle.list("realm")}:
            problems.append(f"{mode_key} names an unknown realm")
    assert problems == [], problems


def test_repaired_modes_name_pools_of_their_own_kind() -> None:
    bundle = ContentBundle.load(DATA)
    for mode_key in REPAIRED_MODES:
        mode = bundle.require("exploration_mode", mode_key)
        assert bundle.has("reward", str(mode["reward_pool_key"])), mode_key
        assert bundle.has("encounter_pool", str(mode["enemy_pool_key"])), mode_key
