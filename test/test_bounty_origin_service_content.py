from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.adventures.rules import bounty_definition
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
BOUNTY_FILE = Path("任务/悬赏.json")
KEY = "bounty.dao_origin_service"


def _copy_data(tmp_path: Path) -> Path:
    target = tmp_path / "data"
    shutil.copytree(DATA, target)
    return target


def _document(root: Path) -> dict:
    return json.loads((root / BOUNTY_FILE).read_text(encoding="utf-8"))


def _write(root: Path, document: dict) -> None:
    (root / BOUNTY_FILE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _record(document: dict) -> dict:
    return next(row for row in document["records"] if row["key"] == KEY)


def test_shipped_bounty_matches_the_frozen_adventures_row() -> None:
    bundle = ContentBundle.load(DATA)
    definition = bounty_definition(KEY, bundle)
    # adventures v0.6: complete three public services, 12 hours.
    assert definition.target_kind == "public_service_completions"
    assert definition.target_key is None
    assert definition.target_amount == 3
    assert definition.duration_seconds == 12 * 3600
    assert definition.daily_limit == 1
    assert definition.reputation_key == "local.dao_service"
    assert definition.required_realm == "dao_union"
    assert definition.runtime_status == "open"


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda row: row.update(target_kind="public_services"), "unsupported target_kind"),
        (lambda row: row.update(target_key="project.town_well"), "target_key must be null"),
        (lambda row: row.update(target_amount=0), "target_amount"),
        (lambda row: row.update(duration_seconds=0), "duration_seconds"),
        (lambda row: row.update(daily_limit=0), "daily_limit"),
        (lambda row: row.update(weight=0), "weight"),
        (lambda row: row.update(reputation_key="nope"), "local reputation key"),
        (lambda row: row.pop("target_kind"), "target_kind"),
    ],
)
def test_malformed_bounty_content_is_rejected(tmp_path: Path, mutate, expected: str) -> None:
    root = _copy_data(tmp_path)
    document = _document(root)
    mutate(_record(document))
    _write(root, document)

    bundle = ContentBundle.load(root)
    with pytest.raises((ContentError, ValueError, KeyError)) as excinfo:
        bounty_definition(KEY, bundle)
    assert expected in str(excinfo.value)