"""A dispatch record's declared stage must be enforced, not just displayed.

Every shipped dispatch declared `stage: mortal` while the preview hardcoded
`>= mortal`, so the parsed field was decorative. This module pins the honest gate
for the two records this phase added and proves the shipped records are unchanged.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_rules import dispatch_definitions

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

SEEKER_DISPATCH = "dispatch.seeker.clinic_run"
CULTIVATOR_DISPATCH = "dispatch.cultivator.herb_convoy"


def _context(user: str, name: str, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter="web", user_id=user, request_id=name, operation_id=operation_id
    )


def _prepare(runtime, user: str, *, stage: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage=?, realm_key='qi_gathering', realm_layer=1, "
            "stamina=200, stamina_max=200, energy=200, energy_max=200 "
            "WHERE platform_user_id=?",
            (stage, user),
        )


def test_shipped_stages_are_declared_and_loadable() -> None:
    bundle = ContentBundle.load(DATA)
    definitions = dispatch_definitions(bundle)
    assert definitions[SEEKER_DISPATCH].required_stage == "seeker"
    assert definitions[CULTIVATOR_DISPATCH].required_stage == "cultivator"
    # Every shipped record declares a supported stage, so the gate has no gaps.
    supported = {"new_user", "mortal", "seeker", "cultivator", "suspended"}
    for key, definition in definitions.items():
        assert definition.required_stage in supported, (key, definition.required_stage)


def test_displayed_requirement_matches_the_declared_stage() -> None:
    from nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_use_cases import (
        DispatchApplication,
    )

    labels = {"seeker": "寻道期", "cultivator": "入道后"}
    bundle = ContentBundle.load(DATA)
    definitions = dispatch_definitions(bundle)
    text = DispatchApplication._requirement_text(
        object.__new__(DispatchApplication), definitions[SEEKER_DISPATCH]
    )
    assert "寻道期" in text, text
    text = DispatchApplication._requirement_text(
        object.__new__(DispatchApplication), definitions[CULTIVATOR_DISPATCH]
    )
    assert "入道后" in text, text
    # The declared stage is the one the label text advertises.
    assert definitions[SEEKER_DISPATCH].required_stage == "seeker"
    assert definitions[CULTIVATOR_DISPATCH].required_stage == "cultivator"
    assert set(labels) == {"seeker", "cultivator"}


def test_seeker_dispatch_refuses_a_mortal_player_and_accepts_a_seeker() -> None:
    async def run() -> None:
        clock_box = [datetime(2026, 9, 30, 12, tzinfo=timezone.utc)]
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=lambda: clock_box[0])
            try:
                # A mortal player cannot take the seeker dispatch: the preview
                # lists the stage as missing and the accept refuses.
                mortal = "dispatch-stage-mortal"
                assert (await runtime.dispatch(_context(mortal, "create"), "开始修仙")).ok
                assert (await runtime.dispatch(_context(mortal, "seek"), "寻仙问道")).ok
                _prepare(runtime, mortal, stage="mortal")
                preview = await runtime.dispatch(
                    _context(mortal, "preview"), "派遣预览 寻道问诊"
                )
                assert preview.ok, preview
                assert "需要寻道期角色" in preview.message, preview.message
                refused = await runtime.dispatch(
                    _context(mortal, "accept", "mortal-accept"),
                    "接受派遣 寻道问诊",
                )
                assert refused.code == "DISPATCH_REQUIREMENT_MISSING", refused

                # A seeker takes it and settles through the shipped engine.
                seeker = "dispatch-stage-seeker"
                assert (await runtime.dispatch(_context(seeker, "create"), "开始修仙")).ok
                assert (await runtime.dispatch(_context(seeker, "seek"), "寻仙问道")).ok
                _prepare(runtime, seeker, stage="seeker")
                accepted = await runtime.dispatch(
                    _context(seeker, "accept", "seeker-accept"),
                    "接受派遣 寻道问诊",
                )
                assert accepted.code == "DISPATCH_ACCEPTED", accepted
            finally:
                await runtime.close()

    asyncio.run(run())
