from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_rules import dispatch_definitions


ROOT = Path(__file__).parents[1]


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _copy_content(target: Path) -> Path:
    content = target / "data"
    shutil.copytree(ROOT / "data", content)
    return content


def _change_dispatch(
    content: Path, dispatch_key: str = "dispatch.town_delivery", **changes: object
) -> None:
    path = content / "生活" / "生活.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    row = next(item for item in document["records"] if item.get("key") == dispatch_key)
    row.update(changes)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")


async def _send(runtime, adapter: str, user: str, operation_id: str, text: str):
    context = CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)
    return await runtime.adapters.dispatch(adapter, context, text)


async def _create_player(runtime, adapter: str, user: str) -> None:
    assert (await _send(runtime, adapter, user, f"{user}-create", "开始修仙")).ok
    assert (await _send(runtime, adapter, user, f"{user}-seek", "寻仙问道")).ok


def _set_reputation(
    runtime,
    adapter: str,
    user: str,
    *,
    local: dict[str, int],
    service: int,
    updated_at: str,
) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?",
            (adapter, user),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(player_id) DO UPDATE SET "
            "local_json = excluded.local_json, service_reputation = excluded.service_reputation, "
            "updated_at = excluded.updated_at",
            (player_id, json.dumps(local), service, updated_at),
        )


def test_dispatch_content_freezes_history_and_closes_new_requests(tmp_path: Path) -> None:
    async def run() -> None:
        content = _copy_content(tmp_path)
        _change_dispatch(
            content,
            desc="替镇中商铺护送今日货物。",
            duration_seconds=1800,
            risk={"weights": {"success": 10000}},
            rewards={
                "success": {
                    "spirit_stones": 77,
                    "local.xuantian.new_town": 5,
                    "service_reputation": 5,
                }
            },
        )
        clock = MutableClock()
        runtime = create_runtime(data_dir=content, clock=clock, adapters=("qq.official", "onebot.v11"))
        starts: dict[str, str] = {}
        assignments: dict[str, str] = {}
        try:
            for adapter in ("qq.official", "onebot.v11"):
                user = f"dispatch-content-{adapter}"
                await _create_player(runtime, adapter, user)
                _set_reputation(
                    runtime,
                    adapter,
                    user,
                    local={"local.xuantian.new_town": 996},
                    service=98,
                    updated_at=clock.value.isoformat(),
                )
                accepted = await _send(runtime, adapter, user, f"{user}-accept", "接受派遣 dispatch.town_delivery")
                assert accepted.code == "DISPATCH_ACCEPTED"
                assert accepted.data["ends_at"].endswith("00:30:00+00:00")
                preview = await _send(runtime, adapter, user, f"{user}-preview", "派遣预览 dispatch.town_delivery")
                assert preview.data["dispatches"][0]["description"] == "替镇中商铺护送今日货物。"
                assert "替镇中商铺护送今日货物。" in preview.message
                starts[adapter] = user
                assignments[adapter] = accepted.data["assignment_id"]
            _change_dispatch(
                content,
                desc="替镇中商铺护送改换后的货物。",
                duration_seconds=7200,
                rewards={"success": {"spirit_stones": 99, "local.xuantian.new_town": 8}},
            )
            locations_path = content / "地图" / "地点.json"
            locations = json.loads(locations_path.read_text(encoding="utf-8"))
            town = next(item for item in locations["records"] if item.get("key") == "xuantian.new_town")
            town["local_reputation_maximum"] = 1
            locations_path.write_text(json.dumps(locations, ensure_ascii=False, indent=2), encoding="utf-8")
            await runtime.close()
            clock.advance(minutes=30)
            runtime = create_runtime(data_dir=content, clock=clock, adapters=("qq.official", "onebot.v11"))
            for adapter, user in starts.items():
                settled = await _send(runtime, adapter, user, f"{user}-settle", "结算派遣")
                assert settled.code == "DISPATCH_SETTLED"
                assert settled.data["reward"] == {
                    "spirit_stones": 77,
                    "local.xuantian.new_town": 4,
                    "service_reputation": 2,
                }
                assert "local.xuantian.new_town" not in settled.message
                assert "dispatch.town_delivery" not in settled.message
                assert "名望 +4" in settled.message
                assert "名望 +5" not in settled.message
                assert "服务信誉 +2" in settled.message
                assert "服务信誉 +5" not in settled.message
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assignment_result = json.loads(
                        connection.execute(
                            "SELECT result_json FROM dispatch_assignments WHERE assignment_id = ?",
                            (assignments[adapter],),
                        ).fetchone()[0]
                    )
                    operation_result = json.loads(
                        connection.execute(
                            "SELECT result_json FROM operations WHERE operation_id = ?",
                            (f"{user}-settle",),
                        ).fetchone()[0]
                    )
                assert assignment_result["reward"] == settled.data["reward"]
                assert operation_result["reward"] == settled.data["reward"]
                replay = await _send(runtime, adapter, user, f"{user}-settle", "结算派遣")
                assert replay.data["idempotent_replay"] is True
                assert replay.data["reward"] == settled.data["reward"]
                accepted = await _send(runtime, adapter, user, f"{user}-accept-new", "接受派遣 dispatch.town_delivery")
                assert accepted.code == "DISPATCH_ACCEPTED"
                assert datetime.fromisoformat(accepted.data["ends_at"]) - datetime.fromisoformat(
                    accepted.data["accepted_at"]
                ) == timedelta(hours=2)
                clock.value = datetime.fromisoformat(accepted.data["ends_at"])
                settled_new = await _send(runtime, adapter, user, f"{user}-settle-new", "结算派遣")
                assert settled_new.data["reward"]["spirit_stones"] == 99
            _change_dispatch(content, status="closed")
            await runtime.close()
            runtime = create_runtime(data_dir=content, clock=clock, adapters=("qq.official", "onebot.v11"))
            for adapter, user in starts.items():
                denied = await _send(runtime, adapter, user, f"{user}-closed", "接受派遣 dispatch.town_delivery")
                assert denied.code == "DISPATCH_REQUIREMENT_MISSING"
                replay = await _send(runtime, adapter, user, f"{user}-accept-new", "接受派遣 dispatch.town_delivery")
                assert replay.data["idempotent_replay"] is True
        finally:
            await runtime.close()

    asyncio.run(run())


def test_dao_service_dispatch_records_actual_reputation_on_both_adapters(tmp_path: Path) -> None:
    async def run() -> None:
        content = _copy_content(tmp_path)
        _change_dispatch(
            content,
            dispatch_key="dispatch.dao_service",
            risk={"weights": {"success": 10000}},
        )
        clock = MutableClock()
        runtime = create_runtime(data_dir=content, clock=clock, adapters=("qq.official", "onebot.v11"))
        players: dict[str, str] = {}
        assignments: dict[str, str] = {}
        end_times: dict[str, str] = {}
        try:
            for adapter in ("qq.official", "onebot.v11"):
                user = f"dao-service-cap-{adapter}"
                players[adapter] = user
                await _create_player(runtime, adapter, user)
                _set_reputation(
                    runtime,
                    adapter,
                    user,
                    local={"local.dao_service": 996},
                    service=98,
                    updated_at=clock.value.isoformat(),
                )
                accepted = await _send(
                    runtime, adapter, user, f"{user}-accept", "接受派遣 dispatch.dao_service"
                )
                assert accepted.code == "DISPATCH_ACCEPTED"
                assert accepted.data["outcome"] == "success"
                assignments[adapter] = accepted.data["assignment_id"]
                end_times[adapter] = accepted.data["ends_at"]

            for adapter, user in players.items():
                clock.value = datetime.fromisoformat(end_times[adapter])
                settle_operation = f"{user}-settle"
                if adapter == "qq.official":
                    def fail(*args, **kwargs):
                        raise sqlite3.OperationalError("injected dispatch ledger failure")

                    with patch.object(runtime.repository, "_record_dispatch_operation", fail):
                        failed = await _send(runtime, adapter, user, settle_operation, "结算派遣")
                    assert failed.code == "PERSISTENCE_ERROR"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        reputation = connection.execute(
                            "SELECT local_json, service_reputation FROM player_reputations "
                            "WHERE player_id = (SELECT id FROM players WHERE platform = ? AND platform_user_id = ?)",
                            (adapter, user),
                        ).fetchone()
                        assert json.loads(reputation[0]) == {"local.dao_service": 996}
                        assert reputation[1] == 98
                        assert connection.execute(
                            "SELECT 1 FROM operations WHERE operation_id = ?", (settle_operation,)
                        ).fetchone() is None
                        assert connection.execute(
                            "SELECT COUNT(*) FROM codex_entries WHERE player_id = "
                            "(SELECT id FROM players WHERE platform = ? AND platform_user_id = ?) "
                            "AND entry_key IN (?, ?)",
                            (
                                adapter,
                                user,
                                "codex.dao.service_origin",
                                "codex.story.dao_service_origin",
                            ),
                        ).fetchone()[0] == 0

                settled = await _send(runtime, adapter, user, settle_operation, "结算派遣")
                assert settled.code == "DISPATCH_SETTLED"
                assert settled.data["reward"] == {
                    "local.dao_service": 4,
                    "service_reputation": 2,
                    "codex.dao.service_origin": 1,
                    "codex.story.dao_service_origin": 1,
                }
                assert "道统服务处名望 +4" in settled.message
                assert "服务信誉 +2" in settled.message
                assert "道统服务处名望 +8" not in settled.message
                assert "服务信誉 +4" not in settled.message
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id, local_json, service_reputation = connection.execute(
                        "SELECT p.id, r.local_json, r.service_reputation FROM players p "
                        "JOIN player_reputations r ON r.player_id = p.id "
                        "WHERE p.platform = ? AND p.platform_user_id = ?",
                        (adapter, user),
                    ).fetchone()
                    assert json.loads(local_json) == {"local.dao_service": 1000}
                    assert service_reputation == 100
                    assignment_result = json.loads(
                        connection.execute(
                            "SELECT result_json FROM dispatch_assignments WHERE assignment_id = ?",
                            (assignments[adapter],),
                        ).fetchone()[0]
                    )
                    operation_result = json.loads(
                        connection.execute(
                            "SELECT result_json FROM operations WHERE operation_id = ?",
                            (settle_operation,),
                        ).fetchone()[0]
                    )
                    assert connection.execute(
                        "SELECT COUNT(*) FROM codex_entries WHERE player_id = ? "
                        "AND entry_key IN (?, ?)",
                        (player_id, "codex.dao.service_origin", "codex.story.dao_service_origin"),
                    ).fetchone()[0] == 2
                assert assignment_result["reward"] == settled.data["reward"]
                assert operation_result["reward"] == settled.data["reward"]
                replay = await _send(runtime, adapter, user, settle_operation, "结算派遣")
                assert replay.data["idempotent_replay"] is True
                assert replay.data["reward"] == settled.data["reward"]

            await runtime.close()
            runtime = create_runtime(data_dir=content, clock=clock, adapters=("qq.official", "onebot.v11"))
            for adapter, user in players.items():
                replay = await _send(runtime, adapter, user, f"{user}-settle", "结算派遣")
                assert replay.data["idempotent_replay"] is True
                assert replay.data["reward"]["local.dao_service"] == 4
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM codex_entries WHERE entry_key IN (?, ?)",
                    ("codex.dao.service_origin", "codex.story.dao_service_origin"),
                ).fetchone()[0] == 4
        finally:
            await runtime.close()

    asyncio.run(run())


def test_dispatch_refund_result_uses_stamina_restored_under_cap(tmp_path: Path) -> None:
    async def run() -> None:
        content = _copy_content(tmp_path)
        _change_dispatch(
            content,
            risk={"weights": {"failed": 10000}},
            failure_refunds={"stamina": 3},
        )
        clock = MutableClock()
        runtime = create_runtime(data_dir=content, clock=clock, adapters=("qq.official", "onebot.v11"))
        end_times: dict[str, str] = {}
        try:
            for adapter in ("qq.official", "onebot.v11"):
                user = f"dispatch-refund-cap-{adapter}"
                await _create_player(runtime, adapter, user)
                accepted = await _send(
                    runtime, adapter, user, f"{user}-accept", "接受派遣 dispatch.town_delivery"
                )
                assert accepted.code == "DISPATCH_ACCEPTED"
                assert accepted.data["outcome"] == "failed"
                end_times[adapter] = accepted.data["ends_at"]
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET stamina = stamina_max WHERE platform = ? AND platform_user_id = ?",
                        (adapter, user),
                    )

            for adapter in ("qq.official", "onebot.v11"):
                user = f"dispatch-refund-cap-{adapter}"
                clock.value = datetime.fromisoformat(end_times[adapter])
                settled = await _send(runtime, adapter, user, f"{user}-settle", "结算派遣")
                assert settled.code == "DISPATCH_SETTLED"
                assert settled.data["reward"] == {}
                assert settled.data["refunded"] == {}
                assert "返还 无产出" in settled.message
                replay = await _send(runtime, adapter, user, f"{user}-settle", "结算派遣")
                assert replay.data["idempotent_replay"] is True
                assert replay.data["refunded"] == {}
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    stamina, maximum = connection.execute(
                        "SELECT stamina, stamina_max FROM players WHERE platform = ? AND platform_user_id = ?",
                        (adapter, user),
                    ).fetchone()
                    assert stamina == maximum
        finally:
            await runtime.close()

    asyncio.run(run())


def test_dispatch_content_rejects_unknown_reward_reference(tmp_path: Path) -> None:
    content = _copy_content(tmp_path)
    _change_dispatch(content, rewards={"success": {"item.missing": 1}})
    with pytest.raises(ContentError, match="dispatch dispatch.town_delivery references inactive item"):
        dispatch_definitions(ContentBundle.load(content))


def test_dispatch_ledger_failure_rolls_back_and_retries() -> None:
    async def run() -> None:
        from unittest.mock import patch

        clock = MutableClock()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("qq.official",))
            try:
                user = "dispatch-ledger"
                await _create_player(runtime, "qq.official", user)
                accepted = await _send(runtime, "qq.official", user, "accept", "接受派遣 dispatch.town_delivery")
                assert accepted.code == "DISPATCH_ACCEPTED"
                recovery_task = runtime._dispatch_recovery_task
                if recovery_task is not None:
                    recovery_task.cancel()
                    try:
                        await recovery_task
                    except asyncio.CancelledError:
                        pass
                    runtime._dispatch_recovery_task = None
                clock.value = datetime.fromisoformat(accepted.data["ends_at"])
                original = runtime.repository._record_dispatch_operation

                def fail(*args, **kwargs):
                    raise sqlite3.OperationalError("injected dispatch ledger failure")

                with patch.object(runtime.repository, "_record_dispatch_operation", fail):
                    failed = await _send(runtime, "qq.official", user, "settle", "结算派遣")
                assert failed.code == "PERSISTENCE_ERROR"
                with runtime.repository._connect() as connection:
                    row = connection.execute(
                        "SELECT status FROM dispatch_assignments WHERE assignment_id = ?", (accepted.data["assignment_id"],)
                    ).fetchone()
                    assert row[0] in {"accepted", "running"}
                    assert connection.execute("SELECT 1 FROM operations WHERE operation_id = 'settle'").fetchone() is None
                runtime.repository._record_dispatch_operation = original
                settled = await _send(runtime, "qq.official", user, "settle", "结算派遣")
                assert settled.code == "DISPATCH_SETTLED"
                replay = await _send(runtime, "qq.official", user, "settle", "结算派遣")
                assert replay.data["idempotent_replay"] is True
            finally:
                await runtime.close()

    asyncio.run(run())
