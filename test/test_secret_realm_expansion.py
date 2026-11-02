from __future__ import annotations

import asyncio
import json
import re
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from combat_fixtures import equip_damage_weapon

from nonebot_plugin_xiuxian_3.adapters.message.markdown import (
    markdown_to_text,
    send_markdown_message,
)
from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.adventures.secret_realm_rules import (
    resolve_secret_realm,
    secret_realm_definitions,
)
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import local_reputation_maximum

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = Path("冒险/秘境.json")
TIME_REALM = "instance.secret_realm.time_garden_echo"
ANCESTRAL_REALM = "instance.secret_realm.ancestral_vein"


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


def _context(adapter: str, user: str, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


async def _send(runtime, adapter: str, user: str, text: str, operation_id: str = ""):
    return await runtime.adapters.dispatch(adapter, _context(adapter, user, operation_id), text)


async def _create_and_promote(
    runtime,
    adapter: str,
    user: str,
    *,
    realm: str,
    layer: int,
    location: str,
    stamina: int = 500,
) -> None:
    assert (await _send(runtime, adapter, user, "开始修仙")).ok
    assert (await _send(runtime, adapter, user, "寻仙问道")).ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key=?, realm_layer=?, location_key=?, "
            "stamina=?, stamina_max=?, max_hp=8000, inventory_json='{}' "
            "WHERE platform=? AND platform_user_id=?",
            (realm, layer, location, stamina, max(stamina, 500), adapter, user),
        )
    equip_damage_weapon(runtime, adapter, user, 3000)


def _stamina(runtime, adapter: str, user: str) -> int:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return int(
            connection.execute(
                "SELECT stamina FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone()[0]
        )


def _inventory(runtime, adapter: str, user: str) -> dict[str, int]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        raw = connection.execute(
            "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()[0]
    return json.loads(raw or "{}")


async def _clear(runtime, adapter: str, user: str, tag: str, label: str) -> dict:
    entered = await _send(runtime, adapter, user, f"进入秘境 {label}", f"{tag}-enter")
    assert entered.code == "SECRET_REALM_ENTERED", entered
    resource = await _send(runtime, adapter, user, "选择秘境节点 资源", f"{tag}-resource")
    assert resource.data["current_node"] == "encounter", resource
    encounter = await _send(runtime, adapter, user, "选择秘境节点 遭遇", f"{tag}-encounter")
    assert encounter.code == "SECRET_REALM_COMBAT_PENDING", encounter
    first_battle = await _send(runtime, adapter, user, "结算秘境", f"{tag}-battle-1")
    assert first_battle.data["status"] == "routing", first_battle
    assert first_battle.data["current_node"] == "choice", first_battle
    choice = await _send(runtime, adapter, user, "选择秘境节点 选择", f"{tag}-choice")
    assert choice.data["current_node"] == "encounter", choice
    second_encounter = await _send(runtime, adapter, user, "选择秘境节点 遭遇", f"{tag}-encounter-2")
    assert second_encounter.code == "SECRET_REALM_COMBAT_PENDING", second_encounter
    settled = await _send(runtime, adapter, user, "结算秘境", f"{tag}-settle")
    assert settled.data["status"] == "settled", settled
    return settled


def _copy_data(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    shutil.copytree(ROOT / "data", data_dir, ignore=shutil.ignore_patterns("*.sqlite3*", "*.db*"))
    return data_dir


def _mutate(data_dir: Path, key: str, mutate) -> None:
    path = data_dir / DATA_FILE
    document = json.loads(path.read_text(encoding="utf-8"))
    record = next(item for item in document["records"] if item["key"] == key)
    mutate(record)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_new_common_secret_realms_are_content_valid_and_source_closed() -> None:
    bundle = ContentBundle.load(ROOT / "data")
    definitions = secret_realm_definitions(bundle)
    assert len(definitions) == 7
    source = bundle.get("source", "source.item.void_materials", include_locked=True) or {}
    closed = set(source.get("asset_keys", ()))
    for item in bundle.list("item"):
        if item.get("gathering_sources"):
            closed.add(item["key"])

    time_realm = definitions[TIME_REALM]
    assert time_realm.label == "时序残响"
    assert time_realm.required_realm == "void_refining" and time_realm.required_layer == 1
    assert time_realm.location_key == "cave.time_garden"
    assert time_realm.node_keys == ("resource", "encounter", "choice", "encounter")
    assert time_realm.stamina_cost == 25 and time_realm.quota_limit == 1
    assert time_realm.first_reward == {"item.herb.time_trace": 2, "spirit_stones": 200}

    ancestral = definitions[ANCESTRAL_REALM]
    assert ancestral.label == "祖灵支脉"
    assert ancestral.required_realm == "soul_transformation" and ancestral.required_layer == 1
    assert ancestral.location_key == "beast.ancestral_lake"
    assert ancestral.stamina_cost == 30 and ancestral.quota_limit == 1
    assert ancestral.first_reward["item.beast_blood"] == 2
    assert ancestral.reputation_key == "local.beast.three_realms_trade_port"

    for definition in (time_realm, ancestral):
        for rewards in (definition.first_reward, *(item for _, item in definition.repeat_reward_pool)):
            for key in rewards:
                if key.startswith("item."):
                    assert key in closed, (definition.key, key)
                elif key.startswith("local."):
                    local_reputation_maximum(key, bundle)
    assert resolve_secret_realm("时园残响", bundle) == TIME_REALM
    assert resolve_secret_realm("祖灵湖支脉", bundle) == ANCESTRAL_REALM


def test_new_secret_realm_content_rejects_bad_references(tmp_path: Path) -> None:
    data_dir = _copy_data(tmp_path)
    _mutate(data_dir, TIME_REALM, lambda r: r.update({"enemy_key": "enemy.not_open"}))
    with pytest.raises(ContentError, match="references an inactive enemy"):
        secret_realm_definitions(ContentBundle.load(data_dir))

    data_dir = _copy_data(tmp_path / "realm")
    _mutate(data_dir, TIME_REALM, lambda r: r.update({"required_realm": "realm.not_open"}))
    with pytest.raises(ContentError, match="references an inactive realm"):
        secret_realm_definitions(ContentBundle.load(data_dir))

    data_dir = _copy_data(tmp_path / "reward")
    _mutate(data_dir, ANCESTRAL_REALM, lambda r: r["first_reward"].update({"item.not_open": 1}))
    with pytest.raises(ContentError, match="references an inactive item"):
        secret_realm_definitions(ContentBundle.load(data_dir))

    data_dir = _copy_data(tmp_path / "alias")
    _mutate(data_dir, TIME_REALM, lambda r: r.update({"aliases": ["灵泉秘境"]}))
    with pytest.raises(ContentError, match="duplicate name or alias"):
        secret_realm_definitions(ContentBundle.load(data_dir))


def test_secret_realm_preview_marks_eligibility_and_exposes_links_and_one_button() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 10, 3, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("qq.official",))
            adapter, user = "qq.official", "realm-expansion-preview"
            try:
                await _create_and_promote(
                    runtime,
                    adapter,
                    user,
                    realm="void_refining",
                    layer=1,
                    location="cave.time_garden",
                )
                preview = await _send(runtime, adapter, user, "秘境预览")
                assert preview.code == "SECRET_REALM_PREVIEW"
                time_entry = next(item for item in preview.data["realms"] if item["instance_key"] == TIME_REALM)
                assert time_entry["eligible"] is True
                assert time_entry["enter_command"] == "进入秘境 时序残响"
                assert "进入（进入秘境 时序残响）" in markdown_to_text(preview.message)
                assert not preview.actions

                single = await _send(runtime, adapter, user, "秘境预览 时序残响")
                assert single.code == "SECRET_REALM_PREVIEW"
                assert len(single.actions) == 1
                assert single.actions[0].command == "进入秘境 时序残响"
                assert single.actions[0].enter is True
                assert "时序残响" in single.message
                assert "command:" not in single.message
                assert len(single.data["realms"]) == 1

                blocked = await _send(runtime, adapter, user, "秘境预览 祖灵支脉")
                assert blocked.code == "SECRET_REALM_PREVIEW"
                assert not blocked.actions
                assert "不在秘境入口" in blocked.message

                # Preview is read-only: no run row, no stamina spent.
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    runs = connection.execute(
                        "SELECT COUNT(*) FROM secret_realm_runs WHERE player_id="
                        "(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                        (adapter, user),
                    ).fetchone()[0]
                assert runs == 0
                assert _stamina(runtime, adapter, user) == 500

                # Special realms keep their own preview command.
                for command in ("秘境预览 界隙裂隙", "秘境预览 不存在的秘境"):
                    rejected = await _send(runtime, adapter, user, command, f"reject-{command}")
                    assert rejected.code == "SECRET_REALM_NOT_FOUND", rejected
                    assert not rejected.actions
                too_many = await _send(runtime, adapter, user, "秘境预览 时序残响 祖灵支脉", "too-many")
                assert too_many.code == "INVALID_SECRET_REALM_COMMAND", too_many
                invalid_enter = await _send(runtime, adapter, user, "进入秘境 不存在", "invalid-enter")
                assert invalid_enter.code == "INVALID_SECRET_REALM_COMMAND", invalid_enter
                assert "时序残响" in invalid_enter.message
                assert "祖灵支脉" in invalid_enter.message
                assert "秘境." not in invalid_enter.message

                bot = FakeBot()
                fallback = await send_markdown_message(
                    bot,
                    SimpleNamespace(),
                    single.message,
                    capabilities=("text",),
                    actions=single.actions,
                )
                assert fallback.sent_format == "text" and fallback.degraded is True
                assert str(bot.sent[0]).endswith("可发送：进入秘境 时序残响")
                assert "command:" not in str(bot.sent[0])

                class FakeQQBot(FakeBot):
                    __module__ = "nonebot.adapters.qq.bot"

                class FakeQQEvent:
                    __module__ = "nonebot.adapters.qq.event"

                qq_bot = FakeQQBot()
                native = await send_markdown_message(
                    qq_bot,
                    FakeQQEvent(),
                    single.message,
                    capabilities=("markdown", "keyboard"),
                    actions=single.actions,
                )
                assert native.sent_format == "markdown+keyboard", native
                assert native.degraded is False
                assert "keyboard" in str(qq_bot.sent[0])
            finally:
                await runtime.close()

    asyncio.run(run())


def test_explore_help_lists_secret_realms_with_readable_links() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            context = CommandContext(adapter="web", user_id="realm-help-reader")
            try:
                result = await runtime.dispatch(context, "修仙帮助 探索")
                assert result.code == "HELP_CATEGORY"
                assert not result.actions
                links = {
                    unquote(payload)
                    for _, payload in re.findall(r"\[([^]]+)\]\(command:([^)]+)\)", result.message)
                }
                for label in (
                    "雾隐秘境",
                    "灵泉小径",
                    "雾隐洞天二层秘境",
                    "云舟秘境",
                    "铁木试炼",
                    "时序残响",
                    "祖灵支脉",
                ):
                    assert label in result.message
                    assert f"进入秘境 {label}" in links
                assert "秘境." not in result.message
                text = markdown_to_text(result.message)
                assert "进入秘境 时序残响" in text and "command:" not in text
            finally:
                await runtime.close()

    asyncio.run(run())


def test_time_garden_echo_first_clear_quota_repeat_and_expiry_refund() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 10, 5, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("onebot.v11",))
            adapter, user = "onebot.v11", "realm-time-garden"
            try:
                await _create_and_promote(
                    runtime, adapter, user, realm="void_refining", layer=1, location="cave.time_garden"
                )
                before = _stamina(runtime, adapter, user)
                first = await _clear(runtime, adapter, user, "time-first", "时序残响")
                assert first.data["reward"] == {"item.herb.time_trace": 2, "spirit_stones": 200}
                assert first.data["first_clear"] is True
                assert _stamina(runtime, adapter, user) == before - 25
                assert _inventory(runtime, adapter, user)["item.herb.time_trace"] == 2

                blocked = await _send(runtime, adapter, user, "进入秘境 时序残响", "time-quota")
                assert blocked.code == "SECRET_REALM_QUOTA_EXHAUSTED"
                quota_preview = await _send(runtime, adapter, user, "秘境预览 时序残响", "time-quota-preview")
                assert quota_preview.code == "SECRET_REALM_PREVIEW"
                assert not quota_preview.actions
                assert "本周期次数已用尽" in quota_preview.message
                clock.advance(days=8)
                second = await _clear(runtime, adapter, user, "time-second", "时序残响")
                assert second.data["first_clear"] is False
                assert second.data["reward"] in ({}, {"item.herb.time_trace": 1})

                other = "realm-time-expiry"
                await _create_and_promote(
                    runtime, adapter, other, realm="void_refining", layer=1, location="cave.time_garden"
                )
                stamina_before = _stamina(runtime, adapter, other)
                entered = await _send(runtime, adapter, other, "进入秘境 时序残响", "time-expire-enter")
                assert entered.code == "SECRET_REALM_ENTERED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE secret_realm_runs SET expires_at=? WHERE run_id=?",
                        ((clock.value - timedelta(seconds=1)).isoformat(), entered.data["run_id"]),
                    )
                expired = await _send(runtime, adapter, other, "结算秘境", "time-expire-settle")
                assert expired.code == "SECRET_REALM_SETTLED"
                assert expired.data["outcome"] == "expired"
                assert expired.data["stamina_refunded"] == 25
                assert _stamina(runtime, adapter, other) == stamina_before
            finally:
                await runtime.close()

    asyncio.run(run())


def test_ancestral_vein_first_clear_restart_and_repeat_pool() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 10, 6, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("onebot.v11",))
            adapter, user = "onebot.v11", "realm-ancestral-vein"
            try:
                await _create_and_promote(
                    runtime,
                    adapter,
                    user,
                    realm="soul_transformation",
                    layer=1,
                    location="beast.ancestral_lake",
                )
                entered = await _send(runtime, adapter, user, "进入秘境 祖灵支脉", "ancestral-enter")
                assert entered.code == "SECRET_REALM_ENTERED"
                await _send(runtime, adapter, user, "选择秘境节点 资源", "ancestral-resource")
                await runtime.close()

                runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("onebot.v11",))
                pending = await _send(runtime, adapter, user, "选择秘境节点 遭遇", "ancestral-pending")
                assert pending.code == "SECRET_REALM_COMBAT_PENDING"
                battle = await _send(runtime, adapter, user, "结算秘境", "ancestral-battle-1")
                assert battle.data["status"] == "routing", battle
                assert battle.data["current_node"] == "choice", battle
                await _send(runtime, adapter, user, "选择秘境节点 选择", "ancestral-choice")
                await _send(runtime, adapter, user, "选择秘境节点 遭遇", "ancestral-pending-2")
                first = await _send(runtime, adapter, user, "结算秘境", "ancestral-first-settle")
                assert first.code == "SECRET_REALM_SETTLED"
                assert first.data["status"] == "settled"
                assert first.data["first_clear"] is True
                assert first.data["reward"] == {
                    "item.beast_blood": 2,
                    "local.beast.three_realms_trade_port": 8,
                    "spirit_stones": 150,
                }
                replay = await _send(runtime, adapter, user, "结算秘境", "ancestral-first-settle")
                assert replay.data["idempotent_replay"] is True
                assert replay.data["reward"] == first.data["reward"]

                clock.advance(days=8)
                second = await _clear(runtime, adapter, user, "ancestral-second", "祖灵支脉")
                assert second.data["first_clear"] is False
                assert second.data["reward"] in ({}, {"item.beast_blood": 1})
                assert _inventory(runtime, adapter, user)["item.beast_blood"] >= 2
            finally:
                await runtime.close()

    asyncio.run(run())
