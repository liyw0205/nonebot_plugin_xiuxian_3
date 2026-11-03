from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.social.partner_task_content import (
    partner_task_defaults,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TASK_FILE = Path("社交/道侣协作.json")
DEFAULTS = "task.partner.endgame.defaults"


def _copy_data(tmp_path: Path) -> Path:
    target = tmp_path / "data"
    shutil.copytree(DATA, target)
    return target


def _document(root: Path) -> dict:
    return json.loads((root / TASK_FILE).read_text(encoding="utf-8"))


def _write(root: Path, document: dict) -> None:
    (root / TASK_FILE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _record(document: dict) -> dict:
    return next(row for row in document["records"] if row["key"] == DEFAULTS)


def test_shipped_task_content_matches_the_frozen_social_row() -> None:
    bundle = ContentBundle.load(DATA)
    assert TASK_FILE.as_posix() in bundle.manifest["files"]

    raw = bundle.require("partner_task", DEFAULTS)
    assert raw["status"] == "active"
    # social v0.6: shared task, each side earns merit, never touches the ending.
    assert raw["required_ending_state"] == "open"
    assert raw["target_kind"] == "endgame_assist_wins"

    record = partner_task_defaults(bundle)
    assert record["window_days"] == 7
    assert record["target_amount"] == 1
    assert record["reward_world_merit"] == 20
    assert record["reward_items"] == {"item.spirit_water": 1}
    assert "道侣协作" in record["aliases"]


def test_reward_items_resolve_and_never_include_endgame_assets() -> None:
    bundle = ContentBundle.load(DATA)
    record = partner_task_defaults(bundle)
    for item_key in record["reward_items"]:
        assert bundle.get("item", item_key, include_locked=False) is not None
        assert item_key not in {
            "item.tribulation_token",
            "item.ascension_certificate",
            "item.tribulation_guard",
            "item.dao_fruit_fragment",
            "item.domain_core",
        }


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda row: row.update(window_days=0), "must be a positive integer"),
        (lambda row: row.update(target_amount=0), "must be a positive integer"),
        (lambda row: row.update(reward_world_merit=0), "must be a positive integer"),
        (lambda row: row.update(required_ending_state="locked"), "unsupported ending state"),
        (lambda row: row.update(target_kind="duel_wins"), "unsupported target kind"),
        (lambda row: row.update(reward_items={}), "reward_items must be a non-empty object"),
        (
            lambda row: row.update(reward_items={"item.nope": 1}),
            "unknown item",
        ),
        (
            lambda row: row.update(reward_items={"item.tribulation_token": 1}),
            "may not pay out the endgame asset",
        ),
        (
            lambda row: row.update(reward_items={"item.ascension_certificate": 1}),
            "may not pay out the endgame asset",
        ),
        (
            lambda row: row.update(reward_items={"item.dao_fruit_fragment": 1}),
            "may not pay out the endgame asset",
        ),
        (
            lambda row: row.update(reward_items={"item.spirit_water": 0}),
            "must be a positive integer",
        ),
        (lambda row: row.update(aliases=["   "]), "malformed alias"),
        (lambda row: row.pop("target_amount"), "missing fields"),
        (lambda row: row.update(status="locked"), "not active"),
    ],
)
def test_malformed_task_content_is_rejected(tmp_path: Path, mutate, expected: str) -> None:
    root = _copy_data(tmp_path)
    document = _document(root)
    mutate(_record(document))
    _write(root, document)

    bundle = ContentBundle.load(root)
    with pytest.raises(ContentError) as excinfo:
        partner_task_defaults(bundle)
    assert expected in str(excinfo.value)