"""Contracts for the daily-cultivation variant slice.

The daily board selects three groups (2/2/3 -> 7 candidates, claim one). This
slice widens each pool with realm-tuned variants, so every added task must
point at content that actually exists: a `mode_key` naming a real exploration
mode, and an operation the router really registers. The earlier version of
this test only checked that the word "exploration" appeared in the operation
name, which let two tasks reference non-existent modes
(`explore.high_order`, `explore.nascent_exploration`) and ship uncompletable.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.events.daily_quest_rules import (
    daily_task_definitions,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PACKAGE = ROOT / "nonebot_plugin_xiuxian_3"

EXPECTED_GROUPS = {"cultivation_exploration": 4, "daily_life": 6, "other": 7}
HIGH_REALM_TASKS = {
    "task.daily.high_order_exploration",
    "task.daily.nascent_exploration",
}
# The non-exploration half of the slice: one daily-life routine and two
# dispatch/idle settlements, all reachable from public commands.
ROUTINE_VARIANTS = {
    "task.daily.spirit_tree_water": "daily_life",
    "task.daily.dispatch_settle": "other",
    "task.daily.idle_claim": "other",
}


@pytest.fixture(scope="module")
def bundle() -> ContentBundle:
    return ContentBundle.load(DATA)


def _emitted_operations() -> set[str]:
    """Collect settlement operation names the package actually writes.

    Every daily source reads the `operations` ledger by `operation_name`, so
    the only trustworthy reference set is the set of names emitted in source.
    """

    pattern = re.compile(r'"((?:[a-z_]+\.)+[a-z_]+)"')
    emitted: set[str] = set()
    for path in PACKAGE.rglob("*.py"):
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            emitted.add(match.group(1))
    return emitted


@pytest.fixture(scope="module")
def definitions(bundle: ContentBundle):
    return daily_task_definitions(bundle)


def test_daily_pools_keep_their_group_shape(definitions) -> None:
    actual = {
        group: sum(definition.group == group for definition in definitions)
        for group in EXPECTED_GROUPS
    }
    assert actual == EXPECTED_GROUPS
    assert len(definitions) == sum(EXPECTED_GROUPS.values()) == 17


def test_every_daily_source_uses_a_real_operation(definitions, bundle) -> None:
    """Each source operation must be a settlement a real content path emits.

    Daily progress is projected from the `operations` ledger, so an operation
    name nothing ever writes silently yields an uncompletable task.
    """

    emitted = _emitted_operations()
    assert emitted, "no settlement operations found in the package"
    for definition in definitions:
        for source in definition.sources:
            assert source.operation in emitted, (
                f"{definition.key} references operation {source.operation} "
                "that no code path emits"
            )


def test_daily_mode_keys_are_open_exploration_modes(definitions, bundle) -> None:
    """Every exploration source must name an active, open exploration mode.

    Only `exploration.settle*` sources carry an `explore.*` mode_key; the
    cultivation task carries a `cultivate.*` key from the cultivation mode
    table, which this assertion deliberately leaves to its own loader.
    """

    open_modes = {
        str(row["key"]) for row in bundle.list("exploration_mode", include_locked=False)
    }
    assert open_modes, "exploration mode content failed to load"
    referenced: dict[str, str] = {}
    for definition in definitions:
        for source in definition.sources:
            if not source.operation.startswith("exploration."):
                continue
            result = source.result or {}
            mode_key = result.get("mode_key")
            if mode_key is None:
                continue
            candidates = mode_key["one_of"] if isinstance(mode_key, dict) else [mode_key]
            for candidate in candidates:
                assert candidate in open_modes, (
                    f"{definition.key} references unknown exploration mode {candidate}"
                )
                referenced[definition.key] = str(candidate)
    # The slice specifically adds realm-tuned exploration variants.
    added = {key: mode for key, mode in referenced.items() if key in HIGH_REALM_TASKS}
    assert set(added) == HIGH_REALM_TASKS
    assert all(mode in open_modes for mode in added.values())


def test_high_realm_variants_gate_above_the_starter_mode(definitions, bundle) -> None:
    """The new variants must target deeper content, not the starter outskirts."""

    modes = {
        str(row["key"]): row for row in bundle.list("exploration_mode", include_locked=False)
    }
    for definition in definitions:
        if definition.key not in HIGH_REALM_TASKS:
            continue
        for source in definition.sources:
            mode = modes[str((source.result or {})["mode_key"])]
            assert mode["required_realm"] != "mortal"
            assert mode["required_realm"] != "qi_sensing"


def test_high_realm_variants_are_reachable_from_claimable_realm_stages(
    definitions, bundle
) -> None:
    """A variant is only fair if the realm it demands can run its place's route."""

    locations = {
        str(row["key"]): row for row in bundle.list("location", include_locked=True)
    }
    modes = {
        str(row["key"]): row for row in bundle.list("exploration_mode", include_locked=False)
    }
    for definition in definitions:
        if definition.key not in HIGH_REALM_TASKS:
            continue
        for source in definition.sources:
            mode = modes[str((source.result or {})["mode_key"])]
            location = locations[str(mode["location_key"])]
            assert location.get("status") == "open", (
                f"{definition.key} targets a non-open location {location['key']}"
            )


def test_routine_variants_fill_the_daily_life_and_other_pools(definitions) -> None:
    """The slice also widens the non-exploration pools, not just exploration."""

    by_key = {definition.key: definition for definition in definitions}
    for key, group in ROUTINE_VARIANTS.items():
        assert key in by_key, f"missing daily variant {key}"
        assert by_key[key].group == group
    # Each variant must stay single-step so it cannot double-credit one action.
    for key in ROUTINE_VARIANTS:
        assert by_key[key].target == 1


def _values_disjoint(left, right) -> bool:
    left_values = set(left["one_of"]) if isinstance(left, dict) else {left}
    right_values = set(right["one_of"]) if isinstance(right, dict) else {right}
    return left_values.isdisjoint(right_values)


def _overlaps(left: dict, right: dict) -> bool:
    """Mirror the rules-layer overlap test: disjoint on any shared field wins."""

    for field in set(left) & set(right):
        if _values_disjoint(left[field], right[field]):
            return False
    return True


def test_no_two_daily_sources_share_an_overlapping_predicate(definitions) -> None:
    """One operation may feed several tasks, but never the same settlement.

    The rules layer rejects overlapping predicates so a single operation cannot
    silently credit two board entries; this pins the shipped content to that
    contract instead of relying on the loader to catch a future edit.
    """

    seen: dict[str, list[tuple[str, dict]]] = {}
    for definition in definitions:
        for source in definition.sources:
            for previous_key, previous in seen.get(source.operation, []):
                if previous_key == definition.key:
                    continue
                assert not _overlaps(previous, source.result), (
                    f"{definition.key} overlaps {previous_key} on {source.operation}"
                )
            seen.setdefault(source.operation, []).append(
                (definition.key, dict(source.result))
            )
