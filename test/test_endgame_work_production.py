from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event as normalize_onebot
from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq
from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.production.rules import random_quality_bp


def _onebot_group_event(content: str):
    from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
    from nonebot.adapters.onebot.v11.event import Sender

    return GroupMessageEvent(
        time=1_735_689_600,
        self_id=9001,
        post_type="message",
        sub_type="normal",
        user_id=1001,
        message_type="group",
        message_id=73001,
        message=Message(content),
        original_message=Message(content),
        raw_message=content,
        font=0,
        sender=Sender(user_id=1001, nickname="OneBot道友"),
        group_id=2002,
    )


def _qq_group_event(content: str):
    from nonebot.adapters.qq.event import GroupMessageCreateEvent
    from nonebot.adapters.qq.models.qq import GroupMemberAuthor

    return GroupMessageCreateEvent(
        id="qq-masterwork-event",
        content=content,
        timestamp="2026-09-24T00:00:00+00:00",
        author=GroupMemberAuthor(
            id="qq-user-raw",
            bot=False,
            member_openid="qq-masterwork-user",
            username="QQ道友",
        ),
        group_id="qq-group-raw",
        group_openid="qq-masterwork-group",
    )


def _context(adapter: str, user_id: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user_id, operation_id=operation_id)


def _ready_order(
    runtime,
    order_id: str,
    *,
    failed_attempt_day: bool = False,
    expired: bool = False,
) -> None:
    now = datetime.now(timezone.utc)
    ends_at = (now - timedelta(hours=25 if expired else 0, seconds=1)).isoformat()
    starts_at = (now - timedelta(days=1)).isoformat() if failed_attempt_day else None
    with sqlite3.connect(runtime.settings.database_path) as connection:
        if starts_at:
            connection.execute(
                "UPDATE production_orders SET starts_at = ?, ends_at = ? WHERE order_id = ?",
                (starts_at, ends_at, order_id),
            )
        else:
            connection.execute(
                "UPDATE production_orders SET ends_at = ? WHERE order_id = ?",
                (ends_at, order_id),
            )


def _operation_id(prefix: str, *, should_succeed: bool) -> str:
    for index in range(1000):
        value = f"{prefix}-{index}"
        roll = random_quality_bp(value)
        if (roll >= 500) == should_succeed:
            return value
    raise AssertionError("could not find a deterministic production test operation")


def test_qq_and_onebot_players_produce_and_deliver_real_endgame_work() -> None:
    qq = normalize_qq(_qq_group_event("开始修仙"))
    onebot = normalize_onebot(_onebot_group_event("开始修仙"))

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            players = (
                ("qq", qq.context, "support", "alchemy", "item.masterwork.support"),
                ("onebot", onebot.context, "body", None, "item.masterwork.body"),
            )
            for prefix, normalized_context, path, subprofession, work_item in players:
                base = normalized_context

                async def dispatch(operation: str, text: str, *, operation_id: str | None = None):
                    context = replace(
                        base,
                        operation_id=operation_id or f"{prefix}-{operation}",
                    )
                    return await runtime.adapters.dispatch(base.adapter, context, text)

                created = await dispatch("create", "开始修仙")
                assert created.code == "PLAYER_CREATED"
                for index, command in enumerate(
                    (
                        "寻仙问道",
                        "完成引导 阅读",
                        "前往近郊",
                        "完成引导 采集",
                        "完成引导 炼丹",
                        f"选择道途 {'辅修 炼丹' if path == 'support' else '体修'}",
                    )
                ):
                    result = await dispatch(f"onboard-{index}", command)
                    assert result.ok, (command, result.code, result.message)

                starting_inventory = (
                    {
                        "item.herb.blood_grass": 20,
                        "item.soul_crystal": 3,
                        "item.domain_core": 3,
                        "item.material.cloud_iron": 15,
                        "item.void_crystal": 10,
                    }
                    if path == "support"
                    else {"item.material.cloud_iron": 40, "item.domain_core": 4}
                )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET realm_key = 'void_refining', realm_layer = 10, "
                        "energy = 100, energy_max = 100, inventory_json = ? "
                        "WHERE platform = ? AND platform_user_id = ?",
                        (json.dumps(starting_inventory), base.adapter, base.user_id),
                    )

                recipe_keys = (
                    (
                        "recipe.masterwork.alchemy",
                        "recipe.masterwork.artifice",
                        "recipe.masterwork.formation",
                    )
                    if path == "support"
                    else ("recipe.masterwork.body", "recipe.masterwork.body")
                )
                for index, recipe_key in enumerate(recipe_keys):
                    preview = await dispatch(f"preview-{index}", f"生产预览 {recipe_key}")
                    assert preview.code == "RECIPE_PREVIEW"
                    assert preview.data["recipe_key"] == recipe_key

                    should_succeed = path == "support" or index == 1
                    start_id = _operation_id(f"{prefix}-{recipe_key}-{index}", should_succeed=should_succeed)
                    started = await dispatch(
                        f"start-{index}", f"开始生产 {recipe_key}", operation_id=start_id
                    )
                    assert started.code == "PRODUCTION_STARTED"
                    replay = await dispatch(
                        f"start-replay-{index}", f"开始生产 {recipe_key}", operation_id=start_id
                    )
                    assert replay.data["idempotent_replay"] is True
                    if path == "body" and index == 0:
                        conflict = await dispatch(
                            "start-conflict",
                            "开始生产 recipe.masterwork.spell",
                            operation_id=start_id,
                        )
                        assert conflict.code == "OPERATION_CONFLICT"
                    _ready_order(
                        runtime,
                        started.data["order_id"],
                        failed_attempt_day=not should_succeed,
                        expired=path == "body" and index == 1,
                    )
                    recovered = path == "body" and index == 1
                    completed = await dispatch(
                        f"complete-{index}", "恢复生产" if recovered else "领取生产"
                    )
                    assert completed.code == ("PRODUCTION_RECOVERED" if recovered else "PRODUCTION_COMPLETED")
                    assert completed.data["success"] is should_succeed
                    if should_succeed:
                        output_key = (
                            recipe_key.replace("recipe.", "item.")
                            if recipe_key != "recipe.masterwork.support"
                            else "item.masterwork.support"
                        )
                        assert completed.data["outputs"] == {output_key: 1}
                    else:
                        assert completed.data["outputs"] == {}
                        assert "item.masterwork.body" not in completed.data["inventory"]
                        assert completed.data["refunds"] == {
                            "item.material.cloud_iron": 10,
                            "item.domain_core": 1,
                        }

                    if index == 0:
                        with sqlite3.connect(runtime.settings.database_path) as connection:
                            snapshot = json.loads(
                                connection.execute(
                                    "SELECT snapshot_json FROM production_orders WHERE order_id = ?",
                                    (started.data["order_id"],),
                                ).fetchone()[0]
                            )
                        assert snapshot["path_key"] == path
                        assert snapshot["subprofession_key"] == subprofession
                        assert snapshot["content_version"] == "content-0.6"
                        assert snapshot["rule_version"] == "production-0.6.0"
                        assert (snapshot["random_quality_bp"] >= 500) is should_succeed

                if path == "support":
                    failed_final_id = _operation_id(f"{prefix}-support-final-fail", should_succeed=False)
                    failed_final = await dispatch(
                        "support-final-fail",
                        "开始生产 recipe.masterwork.support",
                        operation_id=failed_final_id,
                    )
                    assert failed_final.code == "PRODUCTION_STARTED"
                    _ready_order(runtime, failed_final.data["order_id"], failed_attempt_day=True)
                    failed_result = await dispatch("support-final-fail-settle", "领取生产")
                    assert failed_result.data["success"] is False
                    assert failed_result.data["outputs"] == {}
                    assert failed_result.data["refunds"] == {
                        "item.masterwork.alchemy": 1,
                        "item.masterwork.artifice": 1,
                        "item.masterwork.formation": 1,
                    }
                    final_id = _operation_id(f"{prefix}-support-final", should_succeed=True)
                    final = await dispatch(
                        "support-final", "开始生产 recipe.masterwork.support", operation_id=final_id
                    )
                    assert final.code == "PRODUCTION_STARTED"
                    _ready_order(runtime, final.data["order_id"])
                    final_result = await dispatch("support-final-settle", "领取生产")
                    assert final_result.data["outputs"] == {"item.masterwork.support": 1}

                delivered = await dispatch("deliver-work", "交付合道作品")
                assert delivered.code == "QUEST_ACTION_RECORDED"
                market = await dispatch(
                    "market-work", f"发布摆摊 {work_item} 1 100"
                )
                assert market.code == "MARKET_ITEM_FORBIDDEN"
                replay_delivery = await dispatch("deliver-work", "交付合道作品")
                assert replay_delivery.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    row = connection.execute(
                        "SELECT inventory_json FROM players WHERE platform = ? AND platform_user_id = ?",
                        (base.adapter, base.user_id),
                    ).fetchone()
                    event = connection.execute(
                        "SELECT payload_json FROM quest_events WHERE player_id = "
                        "(SELECT id FROM players WHERE platform = ? AND platform_user_id = ?) "
                        "AND quest_key = 'quest.dao_union' AND component_key = 'endgame_work'",
                        (base.adapter, base.user_id),
                    ).fetchone()
                assert json.loads(row[0]).get(work_item, 0) == 0
                assert json.loads(event[0])["item_key"] == work_item
            await runtime.close()

    asyncio.run(run())


def test_endgame_work_recipes_enforce_path_before_debiting_resources() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            context = _context("qq.official", "wrong-path", "create")
            assert (await runtime.dispatch(context, "开始修仙")).code == "PLAYER_CREATED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', path_key='spell', realm_key='void_refining', "
                    "realm_layer=10, energy=30, inventory_json=? WHERE platform_user_id=?",
                    (json.dumps({"item.material.cloud_iron": 20, "item.domain_core": 2}), context.user_id),
                )
            blocked = await runtime.dispatch(
                replace(context, operation_id="wrong-path-start"), "开始生产 recipe.masterwork.body"
            )
            assert blocked.code == "RECIPE_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                state = connection.execute(
                    "SELECT energy, inventory_json FROM players WHERE platform_user_id=?", (context.user_id,)
                ).fetchone()
            assert state[0] == 30
            assert json.loads(state[1]) == {"item.material.cloud_iron": 20, "item.domain_core": 2}

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET path_key='support', subprofession_key=NULL, inventory_json=? "
                    "WHERE platform_user_id=?",
                    (json.dumps({"item.herb.blood_grass": 20, "item.soul_crystal": 3, "item.domain_core": 1}), context.user_id),
                )
            missing_subprofession = await runtime.dispatch(
                replace(context, operation_id="missing-subprofession-start"),
                "开始生产 recipe.masterwork.alchemy",
            )
            assert missing_subprofession.code == "RECIPE_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                state = connection.execute(
                    "SELECT energy, inventory_json FROM players WHERE platform_user_id=?", (context.user_id,)
                ).fetchone()
            assert state[0] == 30
            assert json.loads(state[1]) == {
                "item.herb.blood_grass": 20,
                "item.soul_crystal": 3,
                "item.domain_core": 1,
            }
            await runtime.close()

    asyncio.run(run())
