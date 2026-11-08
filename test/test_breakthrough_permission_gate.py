"""A quest that declares `breakthrough_permission` must actually gate it.

`quest.break_void.reward.breakthrough_permission: "void_refining"` was never
read: the claim paid a hardcoded recipe item nobody consumes and the 炼虚
breakthrough opened for anyone at 化神 L10 with the cultivation.  The record is
now the authority for both the payout and the gate.
"""

from __future__ import annotations

import asyncio
import copy
import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from combat_fixtures import BALANCED_QUALIFICATION
from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.quests.rules import (
    breakthrough_permissions,
    permit_rewards,
)

DATA = Path(__file__).resolve().parents[1] / "data"
VOID_QUEST = "quest.break_void"


def _ctx(user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter="web", user_id=user, request_id=operation_id, operation_id=operation_id)


def _bundle() -> ContentBundle:
    return ContentBundle.load(DATA)


def _with_reward(bundle: ContentBundle, quest_key: str, **reward: object) -> ContentBundle:
    records = dict(bundle._records)
    row = copy.deepcopy(records[("quest", quest_key)])
    row["reward"] = {**row["reward"], **reward}
    records[("quest", quest_key)] = row
    return replace(bundle, _records=records)


def _prepare_void_player(runtime, user: str, *, permitted: bool) -> None:
    flags = [VOID_QUEST] if permitted else []
    with sqlite3.connect(runtime.settings.database_path) as db:
        db.execute(
            "UPDATE players SET stage='cultivator', realm_key='soul_transformation', realm_layer=10, "
            "cultivation=500000, total_cultivation=848960, spirit_stones=100000, world_merit=1000, "
            "domain_charge=150, domain_power=500, location_key='void.first_route', stamina=100, "
            "stamina_max=100, inventory_json=?, intro_json=?, qualification_json=? "
            "WHERE platform_user_id=? AND platform='web'",
            (
                json.dumps({"item.void_crystal": 5, "item.void_anchor": 5}),
                json.dumps({"flags": flags}),
                json.dumps(BALANCED_QUALIFICATION),
                user,
            ),
        )


def _assets(runtime) -> tuple:
    with sqlite3.connect(runtime.settings.database_path) as db:
        return db.execute(
            "SELECT spirit_stones, world_merit, inventory_json, total_cultivation FROM players"
            " WHERE platform='web' AND platform_user_id='void-probe'"
        ).fetchone()


def test_the_record_declares_the_void_refining_permit_and_no_dead_item() -> None:
    assert breakthrough_permissions() == {"void_refining": VOID_QUEST}
    items, permission = permit_rewards(VOID_QUEST)
    assert permission == "void_refining"
    # The old hardcoded recipe item had no consumer anywhere; the record never
    # declared it, so the data-driven payout is empty.
    assert items == {}


@pytest.mark.parametrize(
    "reward, message",
    [
        ({"breakthrough_permission": "not_a_realm"}, "unknown realm"),
        ({"breakthrough_permission": 7}, "invalid breakthrough permission"),
        ({"item.not_an_item": 1}, "unknown item"),
        ({"blessing": 1}, "unsupported reward"),
        ({"preparation_bp": 0}, "invalid preparation_bp"),
    ],
)
def test_broken_permit_rewards_are_rejected(reward: dict, message: str) -> None:
    bundle = _with_reward(_bundle(), VOID_QUEST, **reward)
    with pytest.raises(ContentError, match=message):
        permit_rewards(VOID_QUEST, bundle)


def test_two_quests_cannot_share_one_permit() -> None:
    bundle = _bundle()
    records = dict(bundle._records)
    source = copy.deepcopy(records[("quest", VOID_QUEST)])
    source["key"] = "quest.break_void_duplicate"
    records[("quest", "quest.break_void_duplicate")] = source
    with pytest.raises(ContentError, match="two quests declare"):
        breakthrough_permissions(replace(bundle, _records=records))


def test_the_gate_refuses_without_the_claim_and_opens_with_it() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "void-probe"
            assert (await runtime.dispatch(_ctx(user, "create"), "开始修仙")).code == "PLAYER_CREATED"
            _prepare_void_player(runtime, user, permitted=False)
            before = _assets(runtime)
            refused = await runtime.dispatch(_ctx(user, "void-refused"), "开始突破 炼虚")
            assert refused.code == "VOID_QUEST_MISSING", refused.message
            assert "许可" in refused.message
            assert _assets(runtime) == before
            with sqlite3.connect(runtime.settings.database_path) as db:
                assert db.execute("SELECT COUNT(*) FROM operations WHERE operation_id='void-refused'").fetchone()[0] == 0
                assert db.execute(
                    "SELECT COUNT(*) FROM breakthrough_sessions"
                ).fetchone()[0] == 0

            _prepare_void_player(runtime, user, permitted=True)
            started = await runtime.dispatch(_ctx(user, "void-allowed"), "开始突破 炼虚")
            assert started.code == "BREAKTHROUGH_STARTED", started.message
            assert started.data["target_realm"] == "void_refining"

    asyncio.run(run())
