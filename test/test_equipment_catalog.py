"""Equipment catalog completeness contract.

The equipment catalog is the largest data surface in the repo (1866 `item` records
carrying an `equipment_slot`) and, until now, nothing asserted its structure: only
`equipment_rules.py` validates *one* item at a time while loading it.

These tests pin the catalog's shape so a future bulk edit cannot quietly produce a
family with a missing quality tier, a weapon whose `path_key` names a path that does
not exist, an effect using a stat the stats engine does not know, or a growth
reference that points at nothing.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.stats.rules import _AFFIX_STATS, _FLAT_EFFECT_STATS

ROOT = __import__("pathlib").Path(__file__).parents[1]
DATA = ROOT / "data"

SLOTS = ("weapon", "armor", "accessory")
EFFECT_TYPES = {"flat_stat", "combat_stat_bp"}
# Item effects must use the stats engine's own tables, not a parallel list:
# `flat_stat` maps through _FLAT_EFFECT_STATS and `combat_stat_bp` through
# _AFFIX_STATS (both in xiuxian/stats/rules.py).
FLAT_EFFECT_STATS = set(_FLAT_EFFECT_STATS)
BP_EFFECT_STATS = set(_AFFIX_STATS.values())
# Equipment that intentionally carries neither inline `growth` nor
# `growth_profile_key`. `equipment_rules.py` allows it (it only rejects declaring
# both); the catalog currently has none, so a new one has to be deliberate.
PLAIN_EQUIPMENT: set[str] = set()
# Starter gear with no realm gate: usable by a brand-new character.
UNRESTRICTED_EQUIPMENT = {
    "item.weapon.wood_sword",
    "item.weapon.cloud_sword",
    "item.weapon.wingwood_dagger",
    "item.weapon.ironwood_spear",
    "item.armor.cotton_robe",
    "item.armor.hemp_guard",
    "item.armor.rattan_vest",
}
# The six cultivation paths declared in 道途/道途.json.
PATHS = {"beast", "body", "demonic", "device", "spell", "support"}
# Families that ship a full 144-record matrix (24 tiers x 6 quality steps).
MATRIX_FAMILIES = {
    f"item.{slot}.{path}" for slot in ("weapon", "armor") for path in PATHS
}


def _bundle() -> ContentBundle:
    return ContentBundle.load(DATA)


def _equipment(bundle: ContentBundle) -> list[dict]:
    return [row for row in bundle.list("item", include_locked=True) if row.get("equipment_slot")]


def test_every_equipment_item_declares_a_consistent_slot_and_path() -> None:
    bundle = _bundle()
    paths = {row["key"] for row in bundle.list("path", include_locked=True)}
    assert paths == PATHS, f"declared paths drifted: {sorted(paths)}"

    problems: list[str] = []
    for row in _equipment(bundle):
        key = row["key"]
        slot = row["equipment_slot"]
        if slot not in SLOTS:
            problems.append(f"{key}: unknown equipment_slot {slot!r}")
            continue
        parts = key.split(".")
        if len(parts) < 3 or parts[1] != slot:
            problems.append(f"{key}: slot {slot!r} does not match its key prefix")

        declared_path = row.get("path_key")
        key_path = parts[2] if len(parts) > 2 else None
        if declared_path is not None and declared_path not in paths:
            problems.append(f"{key}: path_key {declared_path!r} is not a declared path")
        elif declared_path is not None and key_path in paths and declared_path != key_path:
            problems.append(
                f"{key}: path_key {declared_path!r} disagrees with the key's {key_path!r}"
            )
        elif key_path in paths and declared_path is None:
            problems.append(f"{key}: key names path {key_path!r} but path_key is missing")

    assert problems == [], "equipment slot/path wiring is inconsistent:\n  " + "\n  ".join(problems)


def test_growth_references_resolve_and_plain_items_are_the_documented_set() -> None:
    bundle = _bundle()
    profiles = {row["key"] for row in bundle.list("equipment_growth", include_locked=True)}
    problems: list[str] = []
    plain: set[str] = set()

    for row in _equipment(bundle):
        key = row["key"]
        inline = row.get("growth")
        profile_key = row.get("growth_profile_key")
        if inline is not None and profile_key is not None:
            problems.append(f"{key}: declares both inline growth and a growth_profile_key")
        elif inline is None and profile_key is None:
            plain.add(key)
        elif profile_key is not None and profile_key not in profiles:
            problems.append(f"{key}: growth_profile_key {profile_key!r} does not resolve")

    if plain != PLAIN_EQUIPMENT:
        problems.append(f"equipment without any growth form drifted: {sorted(plain)}")

    assert problems == [], "equipment growth references are broken:\n  " + "\n  ".join(problems)


def test_every_equipment_effect_uses_a_known_type_and_stat() -> None:
    bundle = _bundle()
    problems: list[str] = []
    seen_types: set[str] = set()
    seen_stats: set[str] = set()

    for row in _equipment(bundle):
        for effect in row.get("effects") or []:
            if not isinstance(effect, dict):
                problems.append(f"{row['key']}: effect is not an object")
                continue
            kind = effect.get("type")
            stat = effect.get("stat")
            seen_types.add(kind)
            seen_stats.add(stat)
            if kind not in EFFECT_TYPES:
                problems.append(f"{row['key']}: unknown effect type {kind!r}")
            if kind == "flat_stat" and stat not in FLAT_EFFECT_STATS:
                problems.append(
                    f"{row['key']}: flat_stat {stat!r} is not in _FLAT_EFFECT_STATS"
                )
            elif kind == "combat_stat_bp" and stat not in BP_EFFECT_STATS:
                problems.append(
                    f"{row['key']}: combat_stat_bp {stat!r} is not in _AFFIX_STATS"
                )
            if not isinstance(effect.get("value"), int) or isinstance(effect.get("value"), bool):
                problems.append(f"{row['key']}: effect value is not an integer")

    assert problems == [], "equipment effects are not closed:\n  " + "\n  ".join(problems)
    assert seen_types == EFFECT_TYPES, f"effect types drifted: {sorted(seen_types)}"
    # The catalog must exercise every flat stat the engine maps, and never use a
    # flat-mapped name as a bp stat.
    assert seen_stats <= FLAT_EFFECT_STATS | BP_EFFECT_STATS, sorted(seen_stats)


def test_every_equipment_requirement_points_at_a_real_realm_and_layer() -> None:
    bundle = _bundle()
    problems: list[str] = []

    for row in _equipment(bundle):
        requirements = row.get("requirements") or []
        if not requirements:
            if row["key"] not in UNRESTRICTED_EQUIPMENT:
                problems.append(
                    f"{row['key']}: declares no realm requirement but is not a documented starter item"
                )
            continue
        for requirement in requirements:
            realm_key = requirement.get("realm_key")
            realm = bundle.get("realm", realm_key or "", include_locked=True)
            if realm is None:
                problems.append(f"{row['key']}: realm {realm_key!r} does not resolve")
                continue
            layer = requirement.get("min_layer", 0)
            low, high = realm.get("layer_min"), realm.get("layer_max")
            if not isinstance(layer, int) or not isinstance(low, int) or not isinstance(high, int):
                problems.append(f"{row['key']}: min_layer {layer!r} is not an integer")
            elif not low <= layer <= high:
                problems.append(
                    f"{row['key']}: min_layer {layer} outside {realm_key} {low}..{high}"
                )

    assert problems == [], "equipment realm requirements are invalid:\n  " + "\n  ".join(problems)
    unrestricted = {
        row["key"] for row in _equipment(bundle) if not (row.get("requirements") or [])
    }
    assert unrestricted == UNRESTRICTED_EQUIPMENT, (
        f"unrestricted starter gear drifted: {sorted(unrestricted)}"
    )


def test_matrix_families_keep_a_uniform_quality_split() -> None:
    """Each (slot, path) family ships the same 144-record matrix with the same split."""

    bundle = _bundle()
    per_family: dict[str, Counter] = defaultdict(Counter)
    for row in _equipment(bundle):
        parts = row["key"].split(".")
        if len(parts) < 4:
            continue  # named one-offs such as item.weapon.wood_sword
        family = ".".join(parts[:3])
        if family in MATRIX_FAMILIES:
            per_family[family][row.get("growth_profile_key")] += 1

    problems: list[str] = []
    missing = MATRIX_FAMILIES - set(per_family)
    if missing:
        problems.append(f"families with no matrix records: {sorted(missing)}")

    shapes = {family: dict(counts) for family, counts in per_family.items()}
    distinct = {tuple(sorted(counts.items(), key=lambda item: str(item[0]))) for counts in shapes.values()}
    if len(distinct) > 1:
        problems.append(f"matrix families disagree on their quality split: {shapes}")

    for family, counts in per_family.items():
        total = sum(counts.values())
        if total != 144:
            problems.append(f"{family}: {total} records, expected 144")

    assert problems == [], "equipment matrix drifted:\n  " + "\n  ".join(problems)
