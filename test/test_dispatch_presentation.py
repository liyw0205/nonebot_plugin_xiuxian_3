from __future__ import annotations

import asyncio
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import unquote

from nonebot_plugin_xiuxian_3.adapters.message.markdown import (
    markdown_to_text,
    send_markdown_message,
)
from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_rules import DISPATCHES, choose_outcome

MID_HIGH = (
    "dispatch.foundation.patrol",
    "dispatch.foundation.escort",
    "dispatch.golden_core.vein_survey",
    "dispatch.golden_core.pill_run",
    "dispatch.nascent.ruins_watch",
    "dispatch.nascent.beast_census",
    "dispatch.soul.domain_relay",
    "dispatch.soul.abyss_manifest",
    "dispatch.void.garden_tending",
    "dispatch.void.route_courier",
)
MID_HIGH_LABELS = {DISPATCHES[key].label for key in MID_HIGH}


def _mid_high_accept_commands(message: str) -> set[str]:
    return {
        command
        for label, command in _links(message)
        if label == "接受"
        and command.removeprefix("接受派遣 ") in MID_HIGH_LABELS
    }


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


def _links(message: str) -> list[tuple[str, str]]:
    return [
        (label, unquote(payload))
        for label, payload in re.findall(r"\[([^]]+)\]\(command:([^)]+)\)", message)
    ]


def _context(adapter: str, user: str, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


async def _send(runtime, adapter: str, user: str, text: str, operation_id: str = ""):
    return await runtime.adapters.dispatch(adapter, _context(adapter, user, operation_id), text)


async def _create_and_promote(
    runtime,
    adapter: str,
    user: str,
    *,
    realm_key: str = "void_refining",
    realm_layer: int = 10,
) -> None:
    assert (await _send(runtime, adapter, user, "开始修仙")).ok
    assert (await _send(runtime, adapter, user, "寻仙问道")).ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage = 'cultivator', realm_key = ?, realm_layer = ?, "
            "stamina = 500, stamina_max = 500, energy = 500, energy_max = 500 "
            "WHERE platform = ? AND platform_user_id = ?",
            (realm_key, realm_layer, adapter, user),
        )


def _forced_dispatch_seed(dispatch_key: str, outcome: str) -> str:
    definition = DISPATCHES[dispatch_key]
    return next(
        seed
        for index in range(10000)
        if (seed := f"forced-{dispatch_key}-{index}")
        and choose_outcome(definition, seed) == outcome
    )


def _force_uuid(seed: str, assignment: str):
    return patch(
        "nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_repository.uuid4",
        side_effect=[SimpleNamespace(hex=seed), SimpleNamespace(hex=assignment)],
    )


def test_dispatch_preview_links_every_ready_mid_high_route() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "onebot.v11", "dispatch-presentation-list"
            try:
                await _create_and_promote(runtime, adapter, user)
                result = await _send(runtime, adapter, user, "派遣预览")
                assert result.code == "DISPATCH_PREVIEW"
                assert not result.actions

                commands = _mid_high_accept_commands(result.message)
                assert commands == {
                    f"接受派遣 {DISPATCHES[key].label}" for key in MID_HIGH
                }
                for key in MID_HIGH:
                    assert DISPATCHES[key].label in result.message
                assert "dispatch." not in result.message

                text = markdown_to_text(result.message)
                assert "接受（接受派遣 雾隐洞天巡护）" in text
                assert "command:" not in text
            finally:
                await runtime.close()

    asyncio.run(run())


def test_dispatch_preview_links_only_routes_meeting_the_realm_gate() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "onebot.v11", "dispatch-presentation-foundation"
            try:
                await _create_and_promote(runtime, adapter, user, realm_key="foundation", realm_layer=1)
                result = await _send(runtime, adapter, user, "派遣预览")
                commands = _mid_high_accept_commands(result.message)
                assert commands == {
                    f"接受派遣 {DISPATCHES[key].label}"
                    for key in ("dispatch.foundation.patrol", "dispatch.foundation.escort")
                }
                assert "不可接受" in result.message
            finally:
                await runtime.close()

    asyncio.run(run())


def test_single_dispatch_preview_has_details_one_button_and_text_fallback() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            clock = MutableClock(datetime(2026, 10, 1, tzinfo=timezone.utc))
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "qq.official", "dispatch-presentation-detail"
            try:
                await _create_and_promote(runtime, adapter, user)
                result = await _send(runtime, adapter, user, "派遣预览 洞天巡护")
                assert result.code == "DISPATCH_PREVIEW"
                assert len(result.actions) == 1
                action = result.actions[0]
                assert action.label == "接受此项派遣"
                assert action.command == "接受派遣 雾隐洞天巡护"
                assert action.enter is True
                assert not [command for label, command in _links(result.message) if label == "接受"]

                for expected in ("前置", "耗时", "成本", "风险", "顺利", "失败返还", "可接受"):
                    assert expected in result.message
                assert "20 分钟" in result.message
                assert "dispatch." not in result.message

                bot = FakeBot()
                fallback = await send_markdown_message(
                    bot,
                    SimpleNamespace(),
                    result.message,
                    capabilities=("text",),
                    actions=result.actions,
                )
                assert fallback.sent_format == "text"
                assert fallback.degraded is True
                assert str(bot.sent[0]).endswith("可发送：接受派遣 雾隐洞天巡护")
                assert "command:" not in str(bot.sent[0])
            finally:
                await runtime.close()

    asyncio.run(run())


def test_dispatch_accept_offers_one_cancel_button_and_settlement_links_back() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            clock = MutableClock(datetime(2026, 10, 1, tzinfo=timezone.utc))
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "qq.official", "dispatch-presentation-actions"
            try:
                await _create_and_promote(runtime, adapter, user)
                seed = _forced_dispatch_seed("dispatch.void.garden_tending", "success")
                with _force_uuid(seed, "garden-presentation"):
                    accepted = await _send(runtime, adapter, user, "接受派遣 花畦打理", "accept-presentation")
                assert accepted.code == "DISPATCH_ACCEPTED"
                assert len(accepted.actions) == 1
                assert accepted.actions[0].command == "取消派遣"
                assert accepted.actions[0].enter is True

                replay = await _send(runtime, adapter, user, "接受派遣 花畦打理", "accept-presentation")
                assert replay.data["idempotent_replay"] is True
                assert not replay.actions

                clock.value = datetime.fromisoformat(accepted.data["ends_at"])
                settled = await _send(runtime, adapter, user, "结算派遣", "settle-presentation")
                assert settled.code == "DISPATCH_SETTLED"
                assert settled.data["outcome"] == "success"
                assert settled.data["reward"]["item.herb.time_trace"] >= 1
                assert "再看派遣" in settled.message
                assert "dispatch." not in settled.message
            finally:
                await runtime.close()

    asyncio.run(run())


def test_life_help_lists_mid_high_dispatches_with_links_and_no_buttons() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            context = CommandContext(adapter="web", user_id="dispatch-help-reader")
            try:
                result = await runtime.dispatch(context, "修仙帮助 生活")
                assert result.code == "HELP_CATEGORY"
                assert not result.actions
                commands = {command for label, command in _links(result.message) if label != "返回修仙指南"}
                for key in MID_HIGH:
                    label = DISPATCHES[key].label
                    assert label in result.message
                    assert f"接受派遣 {label}" in commands
                assert "接受派遣 道统服务" in commands
                assert "dispatch." not in result.message
                assert result.message.count("返回修仙指南") == 1

                text = markdown_to_text(result.message)
                assert "接受派遣 雾隐洞天巡护" in text
                assert "command:" not in text
            finally:
                await runtime.close()

    asyncio.run(run())
