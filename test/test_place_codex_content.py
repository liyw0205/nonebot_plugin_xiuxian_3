from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError

ROOT = Path(__file__).resolve().parents[1]
ENTRY_FILE = Path("图鉴/条目.json")
LOC_FILE = Path("地图/地点.json")


def _copy_data(tmp_path: Path, name: str) -> Path:
    data_dir = tmp_path / name
    shutil.copytree(
        ROOT / "data", data_dir, ignore=shutil.ignore_patterns("*.sqlite3*", "*.db*")
    )
    return data_dir


def _mutate(data_dir: Path, relative: Path, key: str, mutate) -> None:
    document = json.loads((data_dir / relative).read_text(encoding="utf-8"))
    for record in document["records"]:
        if record["key"] == key:
            mutate(record)
            break
    else:
        raise AssertionError(f"record {key} not found in {relative}")
    (data_dir / relative).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def test_every_location_is_wired_to_an_existing_place_codex() -> None:
    bundle = ContentBundle.load(ROOT / "data")
    locations = bundle.list("location", include_locked=False)
    assert locations, "no locations loaded"
    for location in locations:
        entry_key = location.get("codex_entry_key")
        assert isinstance(entry_key, str) and entry_key.startswith("codex.place."), (
            f"{location['key']} is not wired to a place codex"
        )
        entry = bundle.get("codex_entry", entry_key, include_locked=False)
        assert entry is not None, f"{location['key']} -> dangling {entry_key}"
        assert entry["category"] == "place"
        assert entry["name"].strip() and entry["desc"].strip()


def test_place_codex_entries_cover_all_thirty_three_locations() -> None:
    bundle = ContentBundle.load(ROOT / "data")
    locations = bundle.list("location", include_locked=True)
    assert len(locations) == 33
    wired = {
        location["codex_entry_key"]
        for location in locations
        if location.get("codex_entry_key")
    }
    place_entries = {
        row["key"]
        for row in bundle.list("codex_entry", include_locked=True)
        if row.get("category") == "place"
    }
    assert wired == place_entries, (
        "every place codex must be referenced by exactly its location"
    )
    assert len(place_entries) == 33


def test_discovery_writes_the_wired_entry(tmp_path: Path) -> None:
    data_dir = _copy_data(tmp_path, "discovery")
    bundle = ContentBundle.load(data_dir)
    garden = bundle.get("location", "cave.time_garden", include_locked=False)
    assert garden["codex_entry_key"] == "codex.place.time_garden"


def test_content_rejects_dangling_codex_wiring(tmp_path: Path) -> None:
    data_dir = _copy_data(tmp_path, "dangling")
    bundle = ContentBundle.load(data_dir)
    # The intact wiring resolves to a real place entry.
    location = bundle.get("location", "cave.time_garden", include_locked=False)
    assert bundle.get("codex_entry", location["codex_entry_key"], include_locked=False)
    # Break it: the world-content guard must reject the dangling key at load.
    _mutate(
        data_dir,
        LOC_FILE,
        "cave.time_garden",
        lambda r: r.update({"codex_entry_key": "codex.place.not_an_entry"}),
    )
    with pytest.raises(ContentError, match="references unknown codex entry"):
        ContentBundle.load(data_dir)


def test_content_rejects_broken_place_entry(tmp_path: Path) -> None:
    data_dir = _copy_data(tmp_path, "broken-entry")
    _mutate(
        data_dir,
        ENTRY_FILE,
        "codex.place.time_garden",
        lambda r: r.pop("desc"),
    )
    bundle = ContentBundle.load(data_dir)
    entry = bundle.get("codex_entry", "codex.place.time_garden", include_locked=True)
    assert entry is not None and not entry.get("desc"), (
        "the mutated entry must have lost its description"
    )
