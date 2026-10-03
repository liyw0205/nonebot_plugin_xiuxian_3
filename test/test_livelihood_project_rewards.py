from __future__ import annotations

import asyncio
import json
import re
import shutil
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event as normalize_onebot_event
from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event
from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


PROJECT_KEY = "project.town_well"
LOCAL_KEY = "local.xuantian.new_town"
LOCATION_KEY = "xuantian.new_town"
WEEK = datetime(2026, 10, 12, tzinfo=timezone.utc)


class MutableClock:
    def __init__(self, value: datetime = WEEK):
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _copy_content(tmp_path: Path) -> Path:
    target = tmp_path / "content"
    shutil.copytree(Path(__file__).parents[1] / "data", target)
    return target


def _edit_content(
    content_dir: Path,
    *,
    label: str = "新镇灵井",
    desc: str = "汇聚木材修复灵井，使新镇委托得到更多库存。",
    stones: int = 30,
    reputation: int = 5,
    cap: int = 6,
) -> None:
    livelihood_path = content_dir / "生活" / "生活.json"
    livelihood = json.loads(livelihood_path.read_text(encoding="utf-8"))
    project = next(row for row in livelihood["records"] if row.get("key") == PROJECT_KEY)
    project["name"] = label
    project["desc"] = desc
    project["requirements"] = {"item.mat.wood": 10}
    project["contribution_resources"] = ["item.mat.wood"]
    project["reward"] = {"spirit_stones": stones, "local_reputation": reputation}
    project["local_reputation_key"] = LOCAL_KEY
    project["reputation_location_key"] = LOCATION_KEY
    livelihood_path.write_text(json.dumps(livelihood, ensure_ascii=False, indent=2), encoding="utf-8")

    locations_path = content_dir / "地图" / "地点.json"
    locations = json.loads(locations_path.read_text(encoding="utf-8"))
    location = next(row for row in locations["records"] if row.get("key") == LOCATION_KEY)
    location["local_reputation_maximum"] = cap
    locations_path.write_text(json.dumps(locations, ensure_ascii=False, indent=2), encoding="utf-8")


def _context(user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter="web", user_id=user, operation_id=operation_id)


async def _prepare_player(runtime, user: str, *, initial_reputation: int = 0) -> tuple[int, str]:
    context = _context(user, f"{user}:create")
    assert (await runtime.dispatch(context, "开始修仙")).ok
    assert (await runtime.dispatch(replace(context, operation_id=f"{user}:seek"), "寻仙问道")).ok
    with runtime.repository._connect() as connection:
        player_id = int(
            connection.execute(
                "SELECT id FROM players WHERE platform = 'web' AND platform_user_id = ?", (user,)
            ).fetchone()[0]
        )
        connection.execute(
            "UPDATE players SET inventory_json = ?, spirit_stones = 100 WHERE id = ?",
            (json.dumps({"item.mat.wood": 10}), player_id),
        )
        connection.execute(
            "INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at) "
            "VALUES (?, ?, 0, ?) ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json",
            (player_id, json.dumps({LOCAL_KEY: initial_reputation}), runtime.repository._now().isoformat()),
        )
    listed = await runtime.dispatch(replace(context, operation_id=f"{user}:list"), "公共项目")
    assert listed.code == "PROJECT_LIST"
    project = next(row for row in listed.data["projects"] if row["project_key"] == PROJECT_KEY)
    contributed = await runtime.dispatch(
        replace(context, operation_id=f"{user}:contribute"),
        f"贡献公共项目 {PROJECT_KEY} 木材 10",
    )
    assert contributed.code == "PROJECT_CONTRIBUTED", contributed
    assert contributed.data["status"] == "active"
    return player_id, project["project_id"]


def _read_assets(runtime, player_id: int) -> tuple[int, str, int, str]:
    with runtime.repository._connect() as connection:
        player = connection.execute(
            "SELECT spirit_stones, inventory_json, cultivation, total_cultivation FROM players WHERE id = ?",
            (player_id,),
        ).fetchone()
        local = connection.execute(
            "SELECT local_json FROM player_reputations WHERE player_id = ?", (player_id,)
        ).fetchone()[0]
    return int(player[0]), str(player[1]), int(player[2]), str(local)


def test_project_reward_and_reputation_cap_are_frozen_across_restart(tmp_path: Path) -> None:
    async def run() -> None:
        content_dir = _copy_content(tmp_path)
        _edit_content(content_dir, stones=30, reputation=5, cap=6)
        clock = MutableClock()
        runtime = create_runtime(data_dir=content_dir, clock=clock)
        player_id, project_id = await _prepare_player(runtime, "frozen-project", initial_reputation=2)
        with runtime.repository._connect() as connection:
            snapshot = json.loads(
                connection.execute(
                    "SELECT snapshot_json FROM livelihood_projects WHERE project_id = ?", (project_id,)
                ).fetchone()[0]
            )
        assert snapshot["label"] == "新镇灵井"
        assert snapshot["desc"] == "汇聚木材修复灵井，使新镇委托得到更多库存。"
        assert snapshot["reward"] == {"local_reputation": 5, "spirit_stones": 30}
        assert snapshot["local_reputation_key"] == LOCAL_KEY
        assert snapshot["reputation_location_key"] == LOCATION_KEY
        assert snapshot["local_reputation_maximum"] == 6
        await runtime.close()

        _edit_content(content_dir, label="改后的灵井", desc="后来改写的灵井说明。", stones=77, reputation=50, cap=500)
        runtime = create_runtime(data_dir=content_dir, clock=clock)
        settled = await runtime.dispatch(_context("frozen-project", "frozen-project:settle"), "结算公共项目")
        assert settled.code == "PROJECT_SETTLED", settled
        assert settled.data["reward"]["spirit_stones"] == 30
        assert settled.data["local_reputation_before"] == 2
        assert settled.data["local_reputation_after"] == 6
        assert settled.data["local_reputation_delta"] == 4
        assert "新镇灵井" in settled.message
        assert "改后的灵井" not in settled.message
        with runtime.repository._connect() as connection:
            assert connection.execute("SELECT spirit_stones FROM players WHERE id = ?", (player_id,)).fetchone()[0] == 130
            assert connection.execute(
                "SELECT snapshot_json FROM livelihood_projects WHERE project_id = ?", (project_id,)
            ).fetchone()[0] == json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
            assert connection.execute(
                "SELECT COUNT(*) FROM livelihood_project_rewards WHERE project_id = ? AND player_id = ?",
                (project_id, player_id),
            ).fetchone()[0] == 1
        await runtime.close()

    asyncio.run(run())


def test_existing_reputation_above_frozen_cap_is_not_reduced_and_delta_is_zero(tmp_path: Path) -> None:
    async def run() -> None:
        content_dir = _copy_content(tmp_path)
        _edit_content(content_dir, reputation=5, cap=6)
        runtime = create_runtime(data_dir=content_dir, clock=MutableClock())
        player_id, _ = await _prepare_player(runtime, "over-cap-project", initial_reputation=12)
        settled = await runtime.dispatch(_context("over-cap-project", "over-cap-project:settle"), "结算公共项目")
        assert settled.code == "PROJECT_SETTLED", settled
        assert settled.data["local_reputation_before"] == 12
        assert settled.data["local_reputation_after"] == 12
        assert settled.data["local_reputation_delta"] == 0
        assert LOCAL_KEY not in settled.data["reward"]
        assert "+0" not in settled.message
        with runtime.repository._connect() as connection:
            local_json = connection.execute(
                "SELECT local_json FROM player_reputations WHERE player_id = ?", (player_id,)
            ).fetchone()[0]
        assert json.loads(local_json)[LOCAL_KEY] == 12
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("failure_point", ["reputation", "reward", "operation"])
def test_project_reward_transaction_rolls_back_and_retries(failure_point: str, tmp_path: Path) -> None:
    async def run() -> None:
        content_dir = _copy_content(tmp_path)
        _edit_content(content_dir)
        runtime = create_runtime(data_dir=content_dir, clock=MutableClock())
        user = f"rollback-{failure_point}"
        player_id, project_id = await _prepare_player(runtime, user, initial_reputation=2)
        before = _read_assets(runtime, player_id)
        with runtime.repository._connect() as connection:
            project_before = tuple(
                connection.execute(
                    "SELECT status, contribution_points, requirements_json, progress_json, result_json "
                    "FROM livelihood_projects WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
            )
        trigger_sql = {
            "reputation": """
                CREATE TRIGGER fail_project_reputation_insert BEFORE INSERT ON player_reputations
                BEGIN SELECT RAISE(ABORT, 'injected reputation failure'); END;
                CREATE TRIGGER fail_project_reputation_update BEFORE UPDATE ON player_reputations
                BEGIN SELECT RAISE(ABORT, 'injected reputation failure'); END;
            """,
            "reward": """
                CREATE TRIGGER fail_project_reward BEFORE INSERT ON livelihood_project_rewards
                BEGIN SELECT RAISE(ABORT, 'injected reward failure'); END;
            """,
            "operation": """
                CREATE TRIGGER fail_project_operation BEFORE INSERT ON operations
                WHEN NEW.operation_name = 'livelihood.settle_project'
                BEGIN SELECT RAISE(ABORT, 'injected operation failure'); END;
            """,
        }[failure_point]
        with runtime.repository._connect() as connection:
            connection.executescript(trigger_sql)
        operation_id = f"{user}:settle"
        failed = await runtime.dispatch(_context(user, operation_id), "结算公共项目")
        assert failed.code == "PERSISTENCE_ERROR", failed
        assert _read_assets(runtime, player_id) == before
        with runtime.repository._connect() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM livelihood_project_rewards WHERE project_id = ? AND player_id = ?",
                (project_id, player_id),
            ).fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM operations WHERE operation_id = ?", (operation_id,)).fetchone()[0] == 0
            assert tuple(
                connection.execute(
                    "SELECT status, contribution_points, requirements_json, progress_json, result_json "
                    "FROM livelihood_projects WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
            ) == project_before
            connection.execute(
                "DROP TRIGGER " + {
                    "reputation": "fail_project_reputation_insert",
                    "reward": "fail_project_reward",
                    "operation": "fail_project_operation",
                }[failure_point]
            )
            if failure_point == "reputation":
                connection.execute("DROP TRIGGER fail_project_reputation_update")

        retried = await runtime.dispatch(_context(user, operation_id), "结算公共项目")
        assert retried.code == "PROJECT_SETTLED", retried
        assert retried.data["reward"]["spirit_stones"] == 30
        assert retried.data["local_reputation_delta"] == 4
        with runtime.repository._connect() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM livelihood_project_rewards WHERE project_id = ? AND player_id = ?",
                (project_id, player_id),
            ).fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM operations WHERE operation_id = ?", (operation_id,)).fetchone()[0] == 1
        await runtime.close()

    asyncio.run(run())


def test_malformed_local_reputation_rejects_project_reward_without_writes(tmp_path: Path) -> None:
    async def run() -> None:
        content_dir = _copy_content(tmp_path)
        _edit_content(content_dir)
        runtime = create_runtime(data_dir=content_dir, clock=MutableClock())
        user = "bad-local-project"
        player_id, project_id = await _prepare_player(runtime, user)
        with runtime.repository._connect() as connection:
            connection.execute("UPDATE player_reputations SET local_json = '{bad' WHERE player_id = ?", (player_id,))
        before = _read_assets(runtime, player_id)
        operation_id = f"{user}:settle"
        result = await runtime.dispatch(_context(user, operation_id), "结算公共项目")
        assert not result.ok
        assert _read_assets(runtime, player_id) == before
        with runtime.repository._connect() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM livelihood_project_rewards WHERE project_id = ? AND player_id = ?",
                (project_id, player_id),
            ).fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM operations WHERE operation_id = ?", (operation_id,)).fetchone()[0] == 0
        await runtime.close()

    asyncio.run(run())


def test_project_settlement_replay_and_operation_conflict_do_not_duplicate_reward(tmp_path: Path) -> None:
    async def run() -> None:
        content_dir = _copy_content(tmp_path)
        _edit_content(content_dir)
        runtime = create_runtime(data_dir=content_dir, clock=MutableClock())
        user = "project-replay"
        player_id, project_id = await _prepare_player(runtime, user)
        operation_id = f"{user}:settle"
        command = "结算公共项目"
        first = await runtime.dispatch(_context(user, operation_id), command)
        replay = await runtime.dispatch(_context(user, operation_id), command)
        assert first.code == replay.code == "PROJECT_SETTLED"
        assert replay.data["idempotent_replay"] is True
        assert replay.data["local_reputation_delta"] == first.data["local_reputation_delta"]
        conflict = await runtime.dispatch(
            _context(user, operation_id), f"结算公共项目 {project_id}"
        )
        assert conflict.code == "OPERATION_CONFLICT"
        with runtime.repository._connect() as connection:
            assert connection.execute("SELECT spirit_stones FROM players WHERE id = ?", (player_id,)).fetchone()[0] == 130
            assert connection.execute(
                "SELECT COUNT(*) FROM livelihood_project_rewards WHERE project_id = ? AND player_id = ?",
                (project_id, player_id),
            ).fetchone()[0] == 1
        await runtime.close()

    asyncio.run(run())


def _onebot_event(content: str, message_id: int, *, user_id: int = 7101):
    from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
    from nonebot.adapters.onebot.v11.event import Sender

    return GroupMessageEvent(
        time=1_735_689_600,
        self_id=9001,
        post_type="message",
        sub_type="normal",
        user_id=user_id,
        message_type="group",
        message_id=message_id,
        message=Message(content),
        original_message=Message(content),
        raw_message=content,
        font=0,
        sender=Sender(user_id=user_id, nickname="道友"),
        group_id=7202,
    )


def _qq_event(content: str, message_id: str, *, user_id: str = "project-qq-user"):
    from nonebot.adapters.qq.event import GroupMessageCreateEvent
    from nonebot.adapters.qq.models.qq import GroupMemberAuthor

    return GroupMessageCreateEvent(
        id=message_id,
        content=content,
        timestamp="2026-10-12T00:00:00+00:00",
        author=GroupMemberAuthor(
            id="qq-raw",
            bot=False,
            member_openid=user_id,
            member_role="member",
            username="道友",
        ),
        group_id="qq-raw-group",
        group_openid="project-qq-group",
    )


@pytest.mark.parametrize("adapter", ["qq.official", "onebot.v11"])
def test_project_rewards_reach_real_adapters_with_player_facing_chinese(adapter: str, tmp_path: Path) -> None:
    async def run() -> None:
        content_dir = _copy_content(tmp_path)
        _edit_content(content_dir)
        runtime = create_runtime(data_dir=content_dir, clock=MutableClock())
        user = "project-qq-user" if adapter == "qq.official" else "7101"

        async def dispatch(index: int, text: str):
            if adapter == "qq.official":
                event = _qq_event(text, f"qq-project-{index}", user_id=user)
                normalized = normalize_qq_event(event)
            else:
                normalized = normalize_onebot_event(_onebot_event(text, 8000 + index))
            return await runtime.adapters.dispatch(adapter, normalized.context, normalized.text)

        assert (await dispatch(0, "开始修仙")).ok
        assert (await dispatch(1, "寻仙问道")).ok
        with runtime.repository._connect() as connection:
            player_id = connection.execute(
                "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?", (adapter, user)
            ).fetchone()[0]
            connection.execute(
                "UPDATE players SET inventory_json = ? WHERE id = ?",
                (json.dumps({"item.mat.wood": 10}), player_id),
            )
        listing = await dispatch(2, "公共项目")
        assert listing.code == "PROJECT_LIST"
        contributed = await dispatch(3, "贡献公共项目 新镇灵井 木材 10")
        assert contributed.code == "PROJECT_CONTRIBUTED", contributed
        settled = await dispatch(4, "结算公共项目")
        assert settled.code == "PROJECT_SETTLED", settled
        for result in (listing, contributed, settled):
            assert not re.search(r"\b(?:project|item|currency|town_commission|route)\.[a-z0-9_.]+", result.message)
            assert not re.search(r"\b(?:proposed|funded|building|active|maintenance_due|inactive|effect_key|status)\b", result.message)
            assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:", result.message)
            assert "项目进度" not in result.message
        assert "本周共建诸事" in listing.message
        assert "众修合力" in listing.message
        assert "共建添力" in contributed.message
        assert "嘉赏已入囊" in settled.message
        assert "灵石" in settled.message
        with runtime.repository._connect() as connection:
            stones = connection.execute("SELECT spirit_stones FROM players WHERE id = ?", (player_id,)).fetchone()[0]
            local = json.loads(
                connection.execute("SELECT local_json FROM player_reputations WHERE player_id = ?", (player_id,)).fetchone()[0]
            )
        assert stones == 130
        assert local[LOCAL_KEY] == 5
        await runtime.close()

    asyncio.run(run())
