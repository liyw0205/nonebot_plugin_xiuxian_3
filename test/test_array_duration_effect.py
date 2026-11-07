"""The bound-order speed bonus is read from the array item's own data.

`item.array.gathering_basic` shipped a `production_duration_multiplier_bp`
effect, but the only live consumer was a hardcoded key + value in the facility
repository. This module proves the bonus now comes from whichever array the
player holds and its declared value.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.items.rules import (
    bound_order_duration_multiplier_bp,
)

DATA = Path(__file__).parents[1] / "data"
GATHERING_ARRAY = "item.array.gathering_basic"


def test_shipped_gathering_array_declares_its_own_multiplier() -> None:
    bundle = ContentBundle.load(DATA)
    record = bundle.require("item", GATHERING_ARRAY)
    effects = [effect for effect in record["effects"] if effect["type"] == "production_duration_multiplier_bp"]
    assert len(effects) == 1, effects
    assert effects[0]["value"] == 9000
    assert effects[0].get("scope") == "bound_order"


def test_held_array_supplies_the_declared_multiplier() -> None:
    bundle = ContentBundle.load(DATA)
    assert bound_order_duration_multiplier_bp({GATHERING_ARRAY: 1}, bundle) == 9000


def test_no_array_means_no_bonus() -> None:
    bundle = ContentBundle.load(DATA)
    assert bound_order_duration_multiplier_bp({}, bundle) is None
    assert bound_order_duration_multiplier_bp({"item.mat.array_sand": 5}, bundle) is None
    # A zero quantity is not holding the array.
    assert bound_order_duration_multiplier_bp({GATHERING_ARRAY: 0}, bundle) is None


def test_strongest_declared_multiplier_wins_and_undeclared_scope_is_ignored(tmp_path: Path) -> None:
    bundle = ContentBundle.load(DATA)
    document = json.loads((DATA / "道具" / "材料.json").read_text(encoding="utf-8"))
    # A second array with a stronger declared value must be honoured.
    document["records"].append(
        {
            "key": "item.array.test_strong",
            "name": "测试强阵",
            "desc": "测试用阵法。",
            "item_type": "array",
            "quality": "rare",
            "stack_limit": 1,
            "instance_mode": "unique",
            "bind_type": "time_bound",
            "bind_duration_seconds": 3600,
            "tradeable": False,
            "effects": [
                {"type": "production_duration_multiplier_bp", "value": 7000, "scope": "bound_order"}
            ],
            "requirements": [],
            "status": "active",
        }
    )
    # A scope other than the bound order must not leak into this bonus.
    document["records"].append(
        {
            "key": "item.array.test_other_scope",
            "name": "测试旁阵",
            "desc": "测试用阵法。",
            "item_type": "array",
            "quality": "rare",
            "stack_limit": 1,
            "instance_mode": "unique",
            "bind_type": "time_bound",
            "bind_duration_seconds": 3600,
            "tradeable": False,
            "effects": [
                {"type": "production_duration_multiplier_bp", "value": 1000, "scope": "sect_order"}
            ],
            "requirements": [],
            "status": "active",
        }
    )
    root = tmp_path / "data"
    shutil.copytree(DATA, root)
    (root / "道具" / "材料.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    local = ContentBundle.load(root)
    assert bound_order_duration_multiplier_bp({GATHERING_ARRAY: 1}, local) == 9000
    assert bound_order_duration_multiplier_bp({"item.array.test_strong": 1}, local) == 7000
    # Stronger (smaller) of two held arrays wins.
    assert (
        bound_order_duration_multiplier_bp(
            {GATHERING_ARRAY: 1, "item.array.test_strong": 1}, local
        )
        == 7000
    )
    # A different scope alone yields no bonus.
    assert bound_order_duration_multiplier_bp({"item.array.test_other_scope": 1}, local) is None
