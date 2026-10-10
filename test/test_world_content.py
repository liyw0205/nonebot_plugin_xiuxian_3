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
        "connections": 64,
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


def test_world_content_rejects_one_way_routes(tmp_path: Path) -> None:
    root = tmp_path / "data"
    shutil.copytree(DATA, root)
    path = root / "地图/区域.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["records"][0]["connections"].pop()
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ContentError, match="bidirectional"):
        validate_world_content(ContentBundle.load(root))
