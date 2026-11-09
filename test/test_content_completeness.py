"""Content completeness contract.

Three defects in the last month came from data that *looked* complete but was not
closed end to end:

* an exploration mode shipped `status=open` while no location listed it, so players
  could not see the entrance;
* a mainline `exploration_reward` objective pointed at an item its own reward pool
  could no longer pay (`item is not attainable`), which surfaced only when another
  stage pinned that pool;
* three enemies declared `stats` in `data/战斗/敌人.json` without a `combat_profile`,
  so `enemy_definition` silently used the Python table and content edits did nothing.

Each invariant below is asserted over the whole bundle and reports *every* violation
at once, so a future regression fails in CI with a file/key list instead of in play.
"""

from __future__ import annotations

import json
from pathlib import Path

from nonebot_plugin_xiuxian_3.xiuxian.combat.rules import enemy_definition
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle

ROOT = Path(__file__).parents[1]
DATA = ROOT / "data"

# Enemies whose combat definition lives in `data/特殊/虚空塔.json` and is resolved by
# the dedicated `enemy.void_spire.` branch of `enemy_definition`; they legitimately
# carry no `combat_profile`.
VOID_SPIRE_ENEMY_COUNT = 18

# The only records allowed outside `active`/`open`, with the reason each is exempt.
ADMIN_ONLY_TOKENS = {"item.token.change_path", "item.token.constitution_reset"}
LOCKED_MODES = {"explore.dao_origin", "explore.tribulation_echo"}


def _bundle() -> ContentBundle:
    return ContentBundle.load(DATA)


def _open_modes(bundle: ContentBundle) -> list[dict]:
    return bundle.list("exploration_mode", include_locked=False)


def _pool_item_rewards(pool: dict) -> set[str]:
    payable: set[str] = set()
    for outcome in pool.get("outcomes") or []:
        for key in (outcome.get("rewards") or {}):
            if isinstance(key, str) and key.startswith("item."):
                payable.add(key)
    return payable


def test_every_open_mode_is_discoverable_and_its_pools_resolve() -> None:
    bundle = _bundle()
    problems: list[str] = []

    for mode in _open_modes(bundle):
        key = mode["key"]
        location_key = mode["location_key"]
        location = bundle.get("location", location_key, include_locked=False)
        if location is None:
            problems.append(f"{key}: location {location_key} is missing or not open")
            continue
        listed = [a for a in location.get("actions", []) if isinstance(a, str)]
        if key not in listed:
            problems.append(f"{key}: not listed in {location_key}.actions (invisible entrance)")

        pool_key = mode.get("reward_pool_key")
        if pool_key and bundle.get("reward", pool_key, include_locked=False) is None:
            problems.append(f"{key}: reward pool {pool_key} does not resolve")

    assert problems == [], "open exploration modes are not closed:\n  " + "\n  ".join(problems)


def test_every_encounter_candidate_resolves_to_an_enemy() -> None:
    bundle = _bundle()
    problems: list[str] = []

    for mode in _open_modes(bundle):
        pool_key = mode.get("enemy_pool_key")
        if not pool_key:
            continue
        pool = bundle.get("encounter_pool", pool_key, include_locked=False)
        if pool is None:
            problems.append(f"{mode['key']}: enemy pool {pool_key} does not resolve")
            continue
        for candidate in pool.get("candidates") or []:
            enemy_key = candidate.get("enemy_key")
            try:
                enemy_definition(enemy_key, content=bundle)
            except Exception as exc:  # noqa: BLE001 - report the reason, keep scanning
                problems.append(
                    f"{mode['key']}: candidate {enemy_key} unresolvable ({type(exc).__name__}: {exc})"
                )

    assert problems == [], "encounter pools reference unusable enemies:\n  " + "\n  ".join(problems)


def test_every_open_mode_has_a_valid_realm_gate() -> None:
    """Link 4: the realm/layer gate must point at a declared realm and a real layer.

    `mortal` is declared `layer_min 0 / layer_max 0`, so `required_layer: 0` is the
    correct encoding for a gate-less mortal mode — compare against the realm's own
    range rather than assuming 1..n.
    """

    bundle = _bundle()
    problems: list[str] = []

    for mode in _open_modes(bundle):
        realm_key = mode.get("required_realm")
        layer = mode.get("required_layer")
        realm = bundle.get("realm", realm_key or "", include_locked=True)
        if realm is None:
            problems.append(f"{mode['key']}: realm {realm_key} does not resolve")
            continue
        low = realm.get("layer_min")
        high = realm.get("layer_max")
        if not isinstance(layer, int) or isinstance(layer, bool):
            problems.append(f"{mode['key']}: required_layer {layer!r} is not an integer")
        elif not isinstance(low, int) or not isinstance(high, int):
            problems.append(f"{realm_key}: realm is missing layer_min/layer_max")
        elif not low <= layer <= high:
            problems.append(
                f"{mode['key']}: required_layer {layer} is outside {realm_key} {low}..{high}"
            )

    assert problems == [], "exploration realm gates are invalid:\n  " + "\n  ".join(problems)


def test_battle_chance_matches_the_declared_enemy_pool() -> None:
    """A mode that can always battle needs an enemy pool, and vice versa."""

    bundle = _bundle()
    problems: list[str] = []

    for mode in _open_modes(bundle):
        chance = int(mode.get("battle_chance_bp", 0))
        pool = mode.get("enemy_pool_key")
        if chance > 0 and not pool:
            problems.append(f"{mode['key']}: battle_chance_bp={chance} but no enemy_pool_key")
        if chance == 0 and pool:
            problems.append(
                f"{mode['key']}: declares enemy pool {pool} but battle_chance_bp=0, so it never fights"
            )

    assert problems == [], "battle wiring is inconsistent:\n  " + "\n  ".join(problems)


def test_every_mainline_exploration_objective_is_payable() -> None:
    bundle = _bundle()
    problems: list[str] = []

    for stage in bundle.list("mainline", include_locked=True):
        for objective in stage.get("objectives") or []:
            kind = objective.get("type")
            if kind not in {"exploration_reward", "exploration_battle_victory"}:
                continue
            mode_key = objective.get("mode_key")
            mode = bundle.get("exploration_mode", mode_key or "", include_locked=True)
            if mode is None:
                problems.append(f"{stage['key']}: objective mode {mode_key} does not resolve")
                continue

            if kind == "exploration_battle_victory":
                if int(mode.get("battle_chance_bp", 0)) <= 0:
                    problems.append(
                        f"{stage['key']}: wants a victory in {mode_key}, "
                        f"but that mode has battle_chance_bp={mode.get('battle_chance_bp')}"
                    )
                continue

            pool_key = mode.get("reward_pool_key")
            pool = bundle.get("reward", pool_key or "", include_locked=True)
            if pool is None:
                problems.append(f"{stage['key']}: pool {pool_key} for {mode_key} does not resolve")
                continue
            wanted = objective.get("item_key")
            payable = _pool_item_rewards(pool)
            if wanted and wanted not in payable:
                problems.append(
                    f"{stage['key']}: objective item {wanted} is not payable by {pool_key} "
                    f"(pool pays: {sorted(payable)})"
                )

    assert problems == [], "mainline objectives are not payable:\n  " + "\n  ".join(problems)


def test_only_void_spire_enemies_are_code_owned() -> None:
    bundle = _bundle()
    code_owned: list[str] = []
    problems: list[str] = []

    for record in bundle.list("enemy", include_locked=True):
        if isinstance(record.get("combat_profile"), dict):
            continue
        key = record["key"]
        code_owned.append(key)
        if not key.startswith("enemy.void_spire."):
            problems.append(f"{key}: declares stats but no combat_profile, so content is ignored")
            continue
        try:
            enemy_definition(key, content=bundle)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{key}: void-spire enemy does not resolve ({type(exc).__name__}: {exc})")

    if len(code_owned) != VOID_SPIRE_ENEMY_COUNT:
        problems.append(
            f"expected exactly {VOID_SPIRE_ENEMY_COUNT} code-owned (void-spire) enemies, "
            f"found {len(code_owned)}: {sorted(code_owned)}"
        )

    assert problems == [], "enemy ownership is not closed:\n  " + "\n  ".join(problems)


def test_modes_and_locations_are_described_consistently() -> None:
    """Every open mode is typeable and every location's codex link resolves."""

    bundle = _bundle()
    problems: list[str] = []
    open_modes = _open_modes(bundle)
    locked = [
        mode["key"]
        for mode in bundle.list("exploration_mode", include_locked=True)
        if mode.get("status") not in ("open", "active")
    ]

    if set(locked) != LOCKED_MODES:
        problems.append(f"locked exploration modes drifted: {sorted(locked)}")

    for mode in open_modes:
        if not mode.get("aliases"):
            problems.append(f"{mode['key']}: no aliases, so the player cannot type it")

    for location in bundle.list("location", include_locked=True):
        codex_key = location.get("codex_entry_key")
        if codex_key and bundle.get("codex_entry", codex_key, include_locked=True) is None:
            problems.append(f"{location['key']}: codex_entry_key {codex_key} does not resolve")

    assert problems == [], "mode/location metadata is inconsistent:\n  " + "\n  ".join(problems)


def test_content_status_surface_matches_the_four_declared_exemptions() -> None:
    manifest = json.loads((DATA / "内容清单.json").read_text(encoding="utf-8"))
    admin_only: set[str] = set()
    locked: dict[str, str] = {}
    unexpected: list[str] = []

    for relative in manifest["files"]:
        path = DATA / relative
        if not path.exists():
            unexpected.append(f"{relative}: declared in 内容清单.json but missing on disk")
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        for record in document.get("records") or []:
            status = record.get("status")
            key = record.get("key")
            if status in ("active", "open", None):
                continue
            if status == "admin_only":
                admin_only.add(key)
            elif status == "locked":
                locked[key] = str(record.get("lock_reason") or "")
            else:
                unexpected.append(f"{relative}::{key}: unexpected status {status!r}")

    problems = list(unexpected)
    if admin_only != ADMIN_ONLY_TOKENS:
        problems.append(f"admin_only set drifted: {sorted(admin_only)}")
    if set(locked) != LOCKED_MODES:
        problems.append(f"locked set drifted: {sorted(locked)}")
    for key, reason in locked.items():
        if not reason.strip():
            problems.append(f"{key}: locked without a lock_reason")

    assert problems == [], "content status surface drifted:\n  " + "\n  ".join(problems)
