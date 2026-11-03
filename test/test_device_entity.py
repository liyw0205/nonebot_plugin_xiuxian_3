from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from urllib.parse import unquote

from combat_fixtures import BALANCED_QUALIFICATION, equip_damage_weapon

from nonebot_plugin_xiuxian_3.adapters.message.markdown import (
    markdown_to_text,
    send_markdown_message,
)
from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime

ENTITY_KEY = "device.scout_doll"
ENTITY_LABEL = "侦查机关"
DUMMY_ENEMY = "enemy.training_dummy"


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[object] = []

    async def send(self, *, event: object, message: object, **kwargs: object) -> dict[str, str]:
        self.sent.append(message)
        return {"message_id": "reply-1"}


def _context(user: str, operation: str = "") -> CommandContext:
    return CommandContext(adapter="onebot.v11", user_id=user, operation_id=operation)


async def _send(runtime, user: str, text: str, operation: str = ""):
    return await runtime.adapters.dispatch("onebot.v11", _context(user, operation), text)


async def _create_player(
    runtime, user: str, *, stones: int = 900, path_key: str = "device", layer: int = 3
) -> None:
    assert (await _send(runtime, user, "开始修仙")).ok
    assert (await _send(runtime, user, "寻仙问道")).ok
    values = {
        "stage": "cultivator",
        "path_key": path_key,
        "realm_key": "qi_sensing",
        "realm_layer": layer,
        "location_key": "xuantian.outskirts",
        "spirit_stones": stones,
        "stamina": 400,
        "stamina_max": 400,
        "qualification_json": json.dumps(BALANCED_QUALIFICATION),
        "inventory_json": json.dumps(
            {"item.mat.wood": 6, "item.ore.ironstone": 4, "item.herb.blood_grass": 5}
        ),
    }
    assignments = ", ".join(f"{key}=?" for key in values)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            f"UPDATE players SET {assignments} WHERE platform='onebot.v11' AND platform_user_id=?",
            (*values.values(), user),
        )


def _player(runtime, user: str):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return connection.execute(
            "SELECT spirit_stones, inventory_json, path_key, realm_layer "
            "FROM players WHERE platform='onebot.v11' AND platform_user_id=?",
            (user,),
        ).fetchone()


def _device_row(runtime, user: str):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return connection.execute(
            "SELECT d.instance_id, d.durability_bp, d.max_durability_bp, d.status, d.deployed "
            "FROM device_instances d JOIN players p ON p.id = d.player_id "
            "WHERE p.platform='onebot.v11' AND p.platform_user_id=?",
            (user,),
        ).fetchone()


def _device_actions(runtime, battle_id: str) -> list[sqlite3.Row]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT round_no, strategy_key, skill_key, damage FROM battle_actions "
            "WHERE battle_id=? AND strategy_key='strategy.device.scout_doll' "
            "ORDER BY sequence_no",
            (battle_id,),
        ).fetchall()


async def _fight(runtime, user: str, *, battle_type: str = "pve.archive_keeper") -> str:
    """Run one full automatic battle and return its id."""

    battle = await runtime.repository.start_quest_battle(
        platform="onebot.v11",
        platform_user_id=user,
        enemy_key=DUMMY_ENEMY,
        battle_type=battle_type,
        operation_id=f"battle:{user}:{battle_type}",
    )
    record = battle
    for _ in range(20):
        if record.status not in {"created", "running"}:
            break
        record = await runtime.repository.run_battle_turn(
            battle_id=battle.battle_id, expected_round=record.round_no + 1
        )
    await runtime.repository.resolve_battle(battle_id=battle.battle_id)
    return battle.battle_id


def test_assemble_deploy_recall_and_repair_round_trip() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "smith")
                stones, inventory, _, _ = _player(runtime, "smith")
                assert stones == 900

                empty = await _send(runtime, "smith", "机关")
                assert empty.ok and empty.code == "DEVICE_STATUS"
                assert empty.data["owned"] == 0
                assert empty.data["assembly_spirit_stones"] == 120
                assert empty.data["assembly_items"] == {
                    "item.mat.wood": 2,
                    "item.ore.ironstone": 1,
                }

                assembled = await _send(runtime, "smith", "组装机关", "assemble-1")
                assert assembled.ok and assembled.code == "DEVICE_ASSEMBLE"
                assert assembled.data["durability_bp"] == 10000
                assert assembled.data["items_spent"] == {
                    "item.mat.wood": 2,
                    "item.ore.ironstone": 1,
                }
                stones_after, inventory_after, _, _ = _player(runtime, "smith")
                assert stones_after == stones - 120
                wood = json.loads(inventory_after)["item.mat.wood"]
                assert wood == json.loads(inventory)["item.mat.wood"] - 2

                row = _device_row(runtime, "smith")
                assert row is not None
                assert row[1] == 10000 and row[3] == "active" and row[4] == 0

                # The one-device cap is enforced by content, not by a counter.
                again = await _send(runtime, "smith", "组装机关", "assemble-2")
                assert not again.ok and again.code == "DEVICE_LIMIT_REACHED"
                assert _player(runtime, "smith")[0] == stones_after

                deployed = await _send(runtime, "smith", "部署机关", "deploy-1")
                assert deployed.ok and deployed.code == "DEVICE_DEPLOY"
                assert deployed.data["deployed"] is True
                assert _device_row(runtime, "smith")[4] == 1

                duplicate = await _send(runtime, "smith", "部署机关", "deploy-2")
                assert not duplicate.ok and duplicate.code == "DEVICE_STATE"

                recalled = await _send(runtime, "smith", "收回机关", "recall-1")
                assert recalled.ok and recalled.code == "DEVICE_RECALL"
                assert _device_row(runtime, "smith")[4] == 0

                not_deployed = await _send(runtime, "smith", "收回机关", "recall-2")
                assert not not_deployed.ok and not_deployed.code == "DEVICE_STATE"

                full = await _send(runtime, "smith", "维修机关", "repair-1")
                assert not full.ok and full.code == "DEVICE_STATE"
                assert _player(runtime, "smith")[0] == stones_after
            finally:
                await runtime.close()

    asyncio.run(run())


def test_repair_restores_damaged_device_and_charges_its_own_cost() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "mender")
                assert (await _send(runtime, "mender", "组装机关", "assemble-1")).ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE device_instances SET durability_bp=8800, status='broken'"
                    )
                stones_before = _player(runtime, "mender")[0]

                repaired = await _send(runtime, "mender", "维修机关", "repair-1")
                assert repaired.ok and repaired.code == "DEVICE_REPAIR"
                assert repaired.data["durability_bp"] == 10000
                assert repaired.data["status"] == "active"
                assert repaired.data["items_spent"] == {"item.mat.wood": 1}
                assert _player(runtime, "mender")[0] == stones_before - 20
            finally:
                await runtime.close()

    asyncio.run(run())


def test_requirements_and_materials_block_assembly_without_writing() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "spellpath", path_key="spell")
                wrong_path = await _send(runtime, "spellpath", "组装机关", "assemble-1")
                assert not wrong_path.ok and wrong_path.code == "DEVICE_REQUIREMENT"
                assert _device_row(runtime, "spellpath") is None
                assert _player(runtime, "spellpath")[0] == 900

                await _create_player(runtime, "pauper", stones=10)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET inventory_json='{}' "
                        "WHERE platform_user_id='pauper'"
                    )
                poor = await _send(runtime, "pauper", "组装机关", "assemble-1")
                assert not poor.ok and poor.code == "DEVICE_MATERIAL_MISSING"
                assert _device_row(runtime, "pauper") is None
                assert _player(runtime, "pauper")[0] == 10
            finally:
                await runtime.close()

    asyncio.run(run())


def test_deployed_device_strikes_and_wears_its_durability_once() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "fighter")
                equip_damage_weapon(runtime, "onebot.v11", "fighter", 6)
                assert (await _send(runtime, "fighter", "组装机关", "assemble-1")).ok
                assert (await _send(runtime, "fighter", "部署机关", "deploy-1")).ok

                battle_id = await _fight(runtime, "fighter")
                actions = _device_actions(runtime, battle_id)
                # Three rounds of participation, at most three strikes.
                assert len(actions) == 3, [dict(row) for row in actions]
                assert [int(row["round_no"]) for row in actions] == [1, 2, 3]
                assert all(row["skill_key"] == ENTITY_KEY for row in actions)
                assert all(int(row["damage"]) > 0 for row in actions)

                row = _device_row(runtime, "fighter")
                assert row[1] == 8800
                assert row[3] == "active"
                assert row[4] == 1

                # Resolving again must not wear the device down twice.
                replay = await runtime.repository.resolve_battle(battle_id=battle_id)
                assert replay.already_completed is True
                assert _device_row(runtime, "fighter")[1] == 8800
            finally:
                await runtime.close()

    asyncio.run(run())


def test_device_wears_out_broken_and_must_be_repaired_before_redeployment() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "worn")
                equip_damage_weapon(runtime, "onebot.v11", "worn", 6)
                assert (await _send(runtime, "worn", "组装机关", "assemble-1")).ok
                assert (await _send(runtime, "worn", "部署机关", "deploy-1")).ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute("UPDATE device_instances SET durability_bp=800")

                await _fight(runtime, "worn")
                row = _device_row(runtime, "worn")
                assert row[1] == 0
                assert row[3] == "broken"
                assert row[4] == 0  # a broken device is recalled automatically

                blocked = await _send(runtime, "worn", "部署机关", "deploy-2")
                assert not blocked.ok and blocked.code == "DEVICE_BROKEN"

                status = await _send(runtime, "worn", "机关")
                assert status.ok and status.data["status"] == "broken"

                repaired = await _send(runtime, "worn", "维修机关", "repair-1")
                assert repaired.ok and repaired.data["status"] == "active"
                # Four repair steps of 2500 bp cover the 10000 bp deficit.
                assert repaired.data["durability_bp"] == 10000
            finally:
                await runtime.close()

    asyncio.run(run())


def test_assembly_replay_is_idempotent_and_survives_a_restart() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "replay")
                first = await _send(runtime, "replay", "组装机关", "assemble-1")
                assert first.ok
                stones_after = _player(runtime, "replay")[0]

                repeated = await _send(runtime, "replay", "组装机关", "assemble-1")
                assert repeated.ok, repeated
                assert repeated.data["already_completed"] is True
                assert repeated.data["instance_id"] == first.data["instance_id"]
                assert _player(runtime, "replay")[0] == stones_after
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    count = connection.execute(
                        "SELECT COUNT(*) FROM device_instances"
                    ).fetchone()[0]
                assert count == 1

                # A Chinese alias resolves to the same stable key, so the same
                # operation replays instead of assembling a second device.
                aliased = await _send(runtime, "replay", "组装机关 机关傀儡", "assemble-1")
                assert aliased.ok
                assert aliased.data["already_completed"] is True
                assert aliased.data["instance_id"] == first.data["instance_id"]
                unknown = await _send(runtime, "replay", "组装机关 不存在的机关", "assemble-9")
                assert not unknown.ok and unknown.code == "DEVICE_NOT_FOUND"
            finally:
                await runtime.close()

            # A restarted process must see the same device and deployment.
            reopened = create_runtime(data_dir=data_dir, clock=clock)
            try:
                assert (await _send(reopened, "replay", "部署机关", "deploy-1")).ok
            finally:
                await reopened.close()
            reopened = create_runtime(data_dir=data_dir, clock=clock)
            try:
                status = await _send(reopened, "replay", "机关")
                assert status.ok
                assert status.data["owned"] == 1
                assert status.data["deployed"] is True
                assert status.data["durability_bp"] == 10000
            finally:
                await reopened.close()

    asyncio.run(run())


def test_rendering_keeps_blue_links_single_action_and_onebot_fallback() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "render")
                empty = await _send(runtime, "render", "机关")
                assert empty.ok
                # No action button before the device exists: only a blue link.
                assert empty.actions == ()
                links = [
                    unquote(match.group(1))
                    for match in re.finditer(r"command:([^)]+)", empty.message)
                ]
                assert links and links[0] == "组装机关"
                text = markdown_to_text(empty.message)
                assert "组装机关" in text
                assert "command:" not in text
                assert ENTITY_KEY not in empty.message

                assert (await _send(runtime, "render", "组装机关", "assemble-1")).ok
                assembled = await _send(runtime, "render", "机关")
                assert assembled.actions
                assert [action.label for action in assembled.actions] == ["部署机关"]

                bot = FakeBot()
                fallback = await send_markdown_message(
                    bot,
                    SimpleNamespace(),
                    assembled.message,
                    capabilities=("text",),
                    actions=assembled.actions,
                )
                assert fallback.sent_format == "text" and fallback.degraded is True
                assert str(bot.sent[0]).endswith(f"可发送：部署机关 {ENTITY_LABEL}")
                assert "command:" not in str(bot.sent[0])

                class FakeQQBot(FakeBot):
                    __module__ = "nonebot.adapters.qq.bot"

                class FakeQQEvent:
                    __module__ = "nonebot.adapters.qq.event"

                qq_bot = FakeQQBot()
                native = await send_markdown_message(
                    qq_bot,
                    FakeQQEvent(),
                    assembled.message,
                    capabilities=("markdown", "keyboard"),
                    actions=assembled.actions,
                )
                assert native.sent_format == "markdown+keyboard", native
                assert native.degraded is False
                assert "keyboard" in str(qq_bot.sent[0])
                assert ENTITY_KEY not in str(qq_bot.sent[0])

                help_page = await _send(runtime, "render", "修仙帮助 生活")
                assert help_page.code == "HELP_CATEGORY"
                assert "机关" in help_page.message
                assert f"组装机关 {ENTITY_LABEL}" in markdown_to_text(help_page.message)
                assert not help_page.actions
            finally:
                await runtime.close()

    asyncio.run(run())