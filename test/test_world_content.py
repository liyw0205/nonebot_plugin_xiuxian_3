from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.world_content import validate_world_content


DATA = Path(__file__).parents[1] / "data"


def test_world_content_has_complete_map_contract() -> None:
    summary = validate_world_content(ContentBundle.load(DATA))

    assert summary == {
        "locations": 33,
        "regions": 10,
        "connections": 65,
        "covered_locations": 33,
    }


@pytest.mark.parametrize(
    ("filename", "mutate", "message"),
    [
        (
            "地图/区域.json",
            lambda row: row["location_keys"].append("location.missing"),
            "unknown locations",
        ),
        (
            "地图/地点.json",
            lambda row: row["requirements"].append(
                {"type": "item", "item_key": "item.missing", "quantity": 1}
            ),
            "unknown item",
        ),
    ],
)
def test_world_content_rejects_dangling_map_references(
    tmp_path: Path, filename: str, mutate, message: str
) -> None:
    root = tmp_path / "data"
    shutil.copytree(DATA, root)
    path = root / filename
    document = json.loads(path.read_text(encoding="utf-8"))
    mutate(document["records"][0])
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ContentError, match=message):
        validate_world_content(ContentBundle.load(root))


def test_world_content_accepts_a_directed_route_without_a_reverse_edge(tmp_path: Path) -> None:
    root = tmp_path / "data"
    shutil.copytree(DATA, root)
    path = root / "地图/区域.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["records"][0]["connections"].pop()
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    summary = validate_world_content(ContentBundle.load(root))
    assert summary["connections"] == 64


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda region: region["connections"].append(dict(region["connections"][0])),
            "duplicate world route",
        ),
        (
            lambda region: region["connections"][0].update(unowned_cost=1),
            "unsupported fields",
        ),
        (
            lambda region: region["connections"][0].update(to="location.missing"),
            "invalid connection",
        ),
        (
            lambda region: region["connections"][0].update(stamina=True),
            "stamina",
        ),
    ],
)
def test_world_content_rejects_invalid_route_records(tmp_path: Path, mutate, message: str) -> None:
    root = tmp_path / "data"
    shutil.copytree(DATA, root)
    path = root / "地图/区域.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    mutate(document["records"][0])
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ContentError, match=message):
        ContentBundle.load(root)


def test_world_content_rejects_location_level_ordinary_travel_costs(tmp_path: Path) -> None:
    root = tmp_path / "data"
    shutil.copytree(DATA, root)
    path = root / "地图/地点.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["records"][0]["travel"] = {"duration_seconds": 1, "stamina": 0}
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ContentError, match="ordinary costs and passes belong to a directed route"):
        ContentBundle.load(root)


def test_world_content_rejects_ambiguous_location_aliases(tmp_path: Path) -> None:
    root = tmp_path / "data"
    shutil.copytree(DATA, root)
    path = root / "地图/地点.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    next(row for row in document["records"] if row["key"] == "xuantian.outskirts")["aliases"] = ["青石镇"]
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ContentError, match="ambiguous"):
        ContentBundle.load(root)


def test_world_content_rejects_arrival_consumption_without_a_route_pass(tmp_path: Path) -> None:
    root = tmp_path / "data"
    shutil.copytree(DATA, root)
    path = root / "地图/区域.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["records"][0]["connections"][0]["consume_pass_on_arrival"] = True
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ContentError, match="without item_key"):
        ContentBundle.load(root)
