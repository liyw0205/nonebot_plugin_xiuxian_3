from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

import pytest

pytest.importorskip("nonebot")

from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event
from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _onebot_event(content: str, message_id: int):
    from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
    from nonebot.adapters.onebot.v11.event import Sender

    return GroupMessageEvent(
        time=1_735_689_600,
        self_id=9001,
        post_type="message",
        sub_type="normal",
        user_id=1001,
        message_type="group",
        message_id=message_id,
        message=Message(content),
        original_message=Message(content),
        raw_message=content,
        font=0,
        sender=Sender(user_id=1001, nickname="OneBot道友"),
        group_id=2002,
    )


def _qq_event(content: str, message_id: str):
    from nonebot.adapters.qq.event import GroupMessageCreateEvent
    from nonebot.adapters.qq.models.qq import GroupMemberAuthor

    return GroupMessageCreateEvent(
        id=message_id,
        content=content,
        timestamp="2026-01-01T00:00:00+00:00",
        author=GroupMemberAuthor(
            id="qq-user-raw",
            bot=False,
            member_openid="qq-user-1",
            member_role="member",
            username="QQ道友",
        ),
        group_id="qq-group-raw",
        group_openid="qq-group-1",
    )


def test_v04_reconstruction_project_gate_and_dual_adapter_reward() -> None:
    async def run() -> None:
        contexts = [
            ("qq", normalize_qq_event(_qq_event("开始修仙", "qq-v04-project")).context),
            ("onebot", normalize_event(_onebot_event("开始修仙", 3204)).context),
        ]
        for prefix, base in contexts:
            clock = MutableClock(datetime(2026, 10, 12, tzinfo=timezone.utc))
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=data_dir, clock=clock)
                async def dispatch(step: str, text: str):
                    return await runtime.adapters.dispatch(
                        base.adapter,
                        replace(base, operation_id=f"{prefix}-v04-{step}"),
                        text,
                    )

                assert (await dispatch("create", "开始修仙")).code == "PLAYER_CREATED"
                assert (await dispatch("seek", "寻仙问道")).code == "SEEKING_STARTED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                        (base.adapter, base.user_id),
                    ).fetchone()[0]
                    connection.execute(
                        """
                        INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
                        VALUES (?, ?, 0, ?)
                        ON CONFLICT(player_id) DO UPDATE SET local_json=excluded.local_json,
                            updated_at=excluded.updated_at
                        """,
                        (
                            player_id,
                            json.dumps({"local.domain_refuge_authorized": 1}, sort_keys=True),
                            clock().isoformat(),
                        ),
                    )
                    connection.execute(
                        "UPDATE players SET inventory_json=? WHERE id=?",
                        (
                            json.dumps(
                                {
                                    "item.mat.wood": 60,
                                    "item.food.coarse_spirit_rice": 60,
                                    "item.pill.healing_low": 20,
                                },
                                sort_keys=True,
                            ),
                            player_id,
                        ),
                    )

                listing = await dispatch("list", "公共项目")
                assert listing.code == "PROJECT_LIST"
                project = next(
                    item for item in listing.data["projects"] if item["project_key"] == "project.domain_refuge"
                )
                assert project["requirements"] == {
                    "item.food.coarse_spirit_rice": 60,
                    "item.mat.wood": 60,
                    "item.pill.healing_low": 20,
                }
                blocked = await dispatch(
                    "blocked",
                    "贡献公共项目 project.domain_refuge 木材 30",
                )
                # The first request consumes the one daily quota; a second
                # contribution on the same UTC day must be rejected.
                assert blocked.code == "PROJECT_CONTRIBUTED"
                assert (await dispatch("blocked-retry", "贡献公共项目 project.domain_refuge 木材 1")).code == "PROJECT_CONTRIBUTION_LIMIT"

                for step, resource, amount in (
                    ("wood-2", "木材", 30),
                    ("rice-1", "灵米", 30),
                    ("rice-2", "灵米", 30),
                    ("pill", "疗伤丹", 20),
                ):
                    clock.advance(days=1)
                    result = await dispatch(step, f"贡献公共项目 project.domain_refuge {resource} {amount}")
                    assert result.code == "PROJECT_CONTRIBUTED", result

                settled = await dispatch("settle", "结算公共项目")
                assert settled.code == "PROJECT_SETTLED", settled
                assert settled.data["reward"]["local_reputation"] == 8
                replay = await dispatch("settle-replay", "结算公共项目")
                assert replay.data["idempotent_replay"] is True

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    local_json, service = connection.execute(
                        "SELECT local_json, service_reputation FROM player_reputations WHERE player_id=?",
                        (player_id,),
                    ).fetchone()
                    local = json.loads(local_json)
                    inventory = json.loads(
                        connection.execute("SELECT inventory_json FROM players WHERE id=?", (player_id,)).fetchone()[0]
                    )
                    assert local["local.domain_refuge"] == 8
                    assert service == 3
                    assert inventory["item.token.construction_coupon"] == 1
                    snapshot = json.loads(
                        connection.execute(
                            "SELECT snapshot_json FROM livelihood_projects WHERE project_key=? ORDER BY id DESC LIMIT 1",
                            ("project.domain_refuge",),
                        ).fetchone()[0]
                    )
                    assert snapshot["content_version"] == "content-0.4"
                    assert snapshot["rule_version"] == "livelihood-0.4.0"
                await runtime.close()

    asyncio.run(run())


def test_v04_projects_are_not_available_without_authority() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            context = normalize_qq_event(_qq_event("开始修仙", "qq-v04-closed")).context
            assert (await runtime.dispatch(context, "开始修仙")).ok
            assert (await runtime.dispatch(replace(context, operation_id="seek"), "寻仙问道")).ok
            result = await runtime.dispatch(
                replace(context, operation_id="closed-project"),
                "贡献公共项目 project.domain_refuge 木材 1",
            )
            assert result.code == "LIVELIHOOD_CONTENT_CLOSED"
            await runtime.close()

    asyncio.run(run())


def test_v04_faction_projects_require_the_matching_trade_station_reputation() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            context = normalize_event(_onebot_event("开始修仙", 3205)).context
            assert (await runtime.dispatch(context, "开始修仙")).ok
            assert (await runtime.dispatch(replace(context, operation_id="seek"), "寻仙问道")).ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                    (context.adapter, context.user_id),
                ).fetchone()[0]
                connection.execute(
                    "UPDATE players SET faction_reputation_json=? WHERE id=?",
                    (json.dumps({"demon": 300, "beast": 299}, sort_keys=True), player_id),
                )
            listing = await runtime.dispatch(context, "公共项目")
            keys = {item["project_key"] for item in listing.data["projects"]}
            assert "project.abyss_purification" in keys
            assert "project.ancestral_habitat" not in keys
            blocked = await runtime.dispatch(
                replace(context, operation_id="ancestral-closed"),
                "贡献公共项目 project.ancestral_habitat 灵米 1",
            )
            assert blocked.code == "LIVELIHOOD_CONTENT_CLOSED"
            await runtime.close()

    asyncio.run(run())
