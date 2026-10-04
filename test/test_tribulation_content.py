from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.progression.endgame_rules import tribulation_definition


class MutableClock:
    def __init__(self) -> None:
        from datetime import datetime, timezone

        self.value = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _ctx(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, request_id=operation, operation_id=operation)


def _copy_content(target: str) -> Path:
    destination = Path(target)
    shutil.copytree(Path(__file__).parents[1] / "data", destination, dirs_exist_ok=True)
    return destination / "事件" / "事件.json"


def _update_event(path: Path, update) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    record = next(row for row in document["records"] if row["key"] == "event.heaven_tribulation")
    update(record)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def _prepare_player(runtime, adapter: str, user: str) -> None:
    created = await runtime.dispatch(_ctx(adapter, user, f"create-{user}"), "开始修仙")
    assert created.ok
    with sqlite3.connect(runtime.settings.database_path) as db:
        db.execute(
            "UPDATE players SET stage='cultivator', realm_key='tribulation', realm_layer=3, "
            "endgame_status='tribulation', location_key='tribulation.sky_terrace', "
            "path_key='body', dao_fruit_progress=280, qualification_json=?, inventory_json=? "
            "WHERE platform=? AND platform_user_id=?",
            (json.dumps({"body": 2000, "agility": 2000}), json.dumps({"item.tribulation_token": 1}), adapter, user),
        )


def test_tribulation_content_is_strict_and_freezes_started_trials() -> None:
    async def run() -> None:
        with TemporaryDirectory() as root:
            data_dir = Path(root) / "data"
            event_path = _copy_content(str(data_dir))
            clock = MutableClock()
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for adapter in ("qq.official", "onebot.v11"):
                user = f"content-freeze-{adapter}"
                await _prepare_player(runtime, adapter, user)
                started = await runtime.dispatch(
                    _ctx(adapter, user, f"start-{user}"), "开始天劫试炼 身心劫"
                )
                assert started.code == "TRIAL_STARTED"
                with sqlite3.connect(runtime.settings.database_path) as db:
                    snapshot = db.execute(
                        "SELECT snapshot_json FROM tribulation_trial_sessions "
                        "JOIN players ON players.id = tribulation_trial_sessions.player_id "
                        "WHERE players.platform=? AND players.platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                frozen = json.loads(snapshot)["trial"]
                assert frozen["name"] == "身心劫"
                assert frozen["progress_reward"] == 100
                assert frozen["duration_seconds"] == 1800

            await runtime.close()
            _update_event(
                event_path,
                lambda record: (
                    record.update(duration_seconds=3600),
                    record["trials"][0].update(name="新身心劫", progress_reward=777),
                ),
            )
            clock.advance(minutes=31)
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for adapter in ("qq.official", "onebot.v11"):
                user = f"content-freeze-{adapter}"
                settled = await runtime.dispatch(
                    _ctx(adapter, user, f"settle-{user}"), "结算天劫试炼"
                )
                assert settled.code == "TRIAL_SUCCEEDED"
                assert settled.data["dao_fruit_progress"] == 380

            new_user = "content-new-onebot"
            await _prepare_player(runtime, "onebot.v11", new_user)
            started = await runtime.dispatch(
                _ctx("onebot.v11", new_user, "start-new"), "开始天劫试炼 新身心劫"
            )
            assert started.code == "TRIAL_STARTED"
            assert started.data["ends_at"].endswith("13:31:00+00:00")
            await runtime.close()

    asyncio.run(run())


def test_tribulation_content_rejects_unknown_reward_item() -> None:
    with TemporaryDirectory() as root:
        data_dir = Path(root) / "data"
        event_path = _copy_content(str(data_dir))
        _update_event(
            event_path,
            lambda record: record["trials"][0]["reward_items"].update({"item.unknown": 1}),
        )
        with pytest.raises(ContentError, match=r"item\.unknown"):
            tribulation_definition(ContentBundle.load(data_dir))


def test_tribulation_content_rejects_unknown_battle_pool() -> None:
    with TemporaryDirectory() as root:
        data_dir = Path(root) / "data"
        event_path = _copy_content(str(data_dir))
        _update_event(
            event_path,
            lambda record: record["trials"][0].update(random_pool="battle.enemy.unknown"),
        )
        with pytest.raises(ContentError, match=r"enemy:enemy\.unknown"):
            tribulation_definition(ContentBundle.load(data_dir))


def test_corrupt_trial_snapshot_is_atomic_and_retryable() -> None:
    async def run() -> None:
        with TemporaryDirectory() as root:
            data_dir = Path(root) / "data"
            _copy_content(str(data_dir))
            clock = MutableClock()
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            await _prepare_player(runtime, "qq.official", "corrupt-snapshot")
            started = await runtime.dispatch(
                _ctx("qq.official", "corrupt-snapshot", "start-corrupt"),
                "开始天劫试炼 身心劫",
            )
            assert started.code == "TRIAL_STARTED"
            with sqlite3.connect(runtime.settings.database_path) as db:
                row = db.execute(
                    "SELECT id, snapshot_json FROM tribulation_trial_sessions "
                    "WHERE session_id=?",
                    (started.data["session_id"],),
                ).fetchone()
                snapshot = json.loads(row[1])
                snapshot["trial"]["reward_items"] = {"item.unknown": 1}
                db.execute(
                    "UPDATE tribulation_trial_sessions SET snapshot_json=? WHERE id=?",
                    (json.dumps(snapshot, ensure_ascii=False, sort_keys=True), row[0]),
                )
            clock.advance(minutes=31)
            rejected = await runtime.dispatch(
                _ctx("qq.official", "corrupt-snapshot", "settle-corrupt"),
                "结算天劫试炼",
            )
            assert rejected.code == "PERSISTENCE_ERROR"
            with sqlite3.connect(runtime.settings.database_path) as db:
                state = db.execute(
                    "SELECT inventory_json, dao_fruit_progress FROM players "
                    "WHERE platform=? AND platform_user_id=?",
                    ("qq.official", "corrupt-snapshot"),
                ).fetchone()
                assert json.loads(state[0]) == {}
                assert state[1] == 280

                snapshot["trial"]["reward_items"] = {"item.dao_fruit_fragment": 1}
                db.execute(
                    "UPDATE tribulation_trial_sessions SET snapshot_json=? WHERE id=?",
                    (json.dumps(snapshot, ensure_ascii=False, sort_keys=True), row[0]),
                )
            retried = await runtime.dispatch(
                _ctx("qq.official", "corrupt-snapshot", "settle-corrupt"),
                "结算天劫试炼",
            )
            assert retried.code == "TRIAL_SUCCEEDED"
            await runtime.close()

    asyncio.run(run())
