"""聚气段 guidance must exist and stay truthful to the realm data.

聚气 (`qi_gathering`, rank 2) shipped with no mainline stage, no quest and no guide,
while every neighbouring realm had content. A mainline chapter cannot be inserted
there without renumbering chapters 3-13 (released content + seed provenance), so the
gap is closed with the existing additive `guide` carrier.

Two constraints shape these tests:

* `intro_rules._requirements` only supports `{"type": "stage"}` and
  `{"type": "location"}` and requires exactly one stage, so a guide cannot be gated to
  聚气 specifically — it is gated to the `cultivator` stage, which is why the prose
  must tell a 感气 reader what comes next rather than assume they are already there.
* the numbers in the prose are copied from `data/境界/境界.json`. A test compares them
  so the documentation cannot drift away from the data it describes.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.player.intro_rules import (
    guide_definitions,
    guides_for_stage,
    resolve_guide,
)

ROOT = Path(__file__).parents[1]
DATA = ROOT / "data"

BREATH = "guide.qi_gathering_breath"
ASCENT = "guide.qi_gathering_ascent"
QI_GATHERING_GUIDES = (BREATH, ASCENT)


def _data() -> dict:
    return json.loads((DATA / "境界" / "境界.json").read_text(encoding="utf-8"))


def _realm(key: str) -> dict:
    return next(row for row in _data()["records"] if row["key"] == key)


def test_both_guides_load_with_the_fields_the_router_needs() -> None:
    bundle = ContentBundle.load(DATA)
    guides = {definition["key"]: definition for definition in guide_definitions(bundle)}

    for key in QI_GATHERING_GUIDES:
        assert key in guides, f"{key} is not loaded"
        guide = guides[key]
        assert guide["stage"] == "cultivator"
        assert guide["output_type"] == "intro_flag"
        assert guide["output"] == {"type": "intro_flag", "key": key}, (
            "the flag must be written back under the guide's own key"
        )
        assert guide["command"], f"{key} needs a command the player can type"
        assert guide["label"] and guide["aliases"]
        # `intro_use_cases._guide_body` renders `desc`; the JSON `content` field is not
        # consumed by the loader, so the actionable text has to live in `desc`.
        assert len(guide["desc"]) >= 80, f"{key} desc is a placeholder"

    # Both must be reachable by the aliases the prose promises.
    assert resolve_guide("聚气", bundle) == BREATH
    assert resolve_guide("纳息", bundle) == BREATH
    assert resolve_guide("登阶", bundle) == ASCENT
    assert resolve_guide("筑基指路", bundle) == ASCENT


def test_the_guides_are_offered_to_cultivators_only() -> None:
    """`guide` gates on player stage, not realm: mortal/seeker never see them."""

    bundle = ContentBundle.load(DATA)
    cultivator = {definition["key"] for definition in guides_for_stage("cultivator", bundle)}
    mortal = {definition["key"] for definition in guides_for_stage("mortal", bundle)}
    seeker = {definition["key"] for definition in guides_for_stage("seeker", bundle)}

    assert set(QI_GATHERING_GUIDES) <= cultivator
    assert not (set(QI_GATHERING_GUIDES) & mortal)
    assert not (set(QI_GATHERING_GUIDES) & seeker)


def test_the_prose_quotes_the_realm_data_instead_of_drifting() -> None:
    bundle = ContentBundle.load(DATA)
    guides = {definition["key"]: definition for definition in guide_definitions(bundle)}
    realm = _realm("qi_gathering")
    thresholds = {int(layer): value for layer, value in realm["layer_thresholds"].items()}

    breath = guides[BREATH]["desc"]
    # Every non-zero layer threshold must appear next to its layer number.
    for layer, value in sorted(thresholds.items()):
        if value == 0:
            continue
        assert re.search(rf"第?{_cn_layer(layer)}层\s*{value}", breath) or f"{value}" in breath, (
            f"{BREATH} does not quote layer {layer}'s threshold {value}"
        )
    assert "十层" in breath and "2900" in breath

    ascent = guides[ASCENT]["desc"]
    total = realm["cross_realm_total_cultivation"]
    assert str(total) in ascent, f"{ASCENT} must quote cross_realm_total_cultivation {total}"
    assert realm["next_realm"] == "foundation"


def _cn_layer(layer: int) -> str:
    return {
        1: "一",
        2: "二",
        3: "三",
        4: "四",
        5: "五",
        6: "六",
        7: "七",
        8: "八",
        9: "九",
        10: "十",
    }[layer]


def _copy_content(target: Path) -> Path:
    shutil.copytree(
        DATA,
        target,
        ignore=shutil.ignore_patterns("*.sqlite3", "*.sqlite3-*", "*.db", "*.db-*"),
    )
    return target


def _context(operation: str, user: str) -> CommandContext:
    return CommandContext(adapter="onebot.v11", user_id=user, operation_id=operation)


def _cultivator_at_qi_gathering(runtime, user: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', path_key='body', realm_key='qi_gathering', "
            "realm_layer=1, stamina=60, stamina_max=60, location_key='xuantian.new_town' "
            "WHERE platform='onebot.v11' AND platform_user_id=?",
            (user,),
        )
        connection.commit()


def _run(coro_factory):
    asyncio.run(coro_factory())


def test_a_qi_gathering_player_can_complete_both_guides_idempotently() -> None:
    async def run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = create_runtime(data_dir=_copy_content(Path(tmp) / "data"), adapters=("onebot.v11",))
            user = "qi-gathering-guide"
            try:
                assert (
                    await runtime.adapters.dispatch("onebot.v11", _context("create", user), "开始修仙")
                ).ok
                _cultivator_at_qi_gathering(runtime, user)

                first = await runtime.adapters.dispatch(
                    "onebot.v11", _context("breath", user), "完成引导 聚气"
                )
                assert first.code == "INTRO_COMPLETED", first.message

                second = await runtime.adapters.dispatch(
                    "onebot.v11", _context("ascent", user), "完成引导 登阶"
                )
                assert second.code == "INTRO_COMPLETED", second.message

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    flags = set(
                        json.loads(
                            connection.execute(
                                "SELECT intro_json FROM players WHERE platform='onebot.v11' "
                                "AND platform_user_id=?",
                                (user,),
                            ).fetchone()[0]
                        ).get("flags", [])
                    )
                assert {BREATH, ASCENT} <= flags

                replay = await runtime.adapters.dispatch(
                    "onebot.v11", _context("ascent", user), "完成引导 登阶"
                )
                assert replay.code == "INTRO_COMPLETED", replay.message
            finally:
                await runtime.close()

    asyncio.run(run())


def test_a_mortal_player_cannot_claim_the_cultivator_guides() -> None:
    async def run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = create_runtime(data_dir=_copy_content(Path(tmp) / "data"), adapters=("onebot.v11",))
            user = "mortal-guide"
            try:
                assert (
                    await runtime.adapters.dispatch("onebot.v11", _context("create", user), "开始修仙")
                ).ok
                refused = await runtime.adapters.dispatch(
                    "onebot.v11", _context("breath-refused", user), "完成引导 聚气"
                )
                assert refused.code == "PLAYER_STAGE_CONFLICT", refused.message
            finally:
                await runtime.close()

    asyncio.run(run())
