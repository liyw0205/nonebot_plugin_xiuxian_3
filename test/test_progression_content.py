from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.progression.rules import (
    CULTIVATION_GUIDANCE,
    cultivation_definitions,
    cultivation_gain,
    layer_unlocks,
    progression_unlock_definitions,
)
from nonebot_plugin_xiuxian_3.xiuxian.progression.milestone_rules import milestone_definitions


class MutableClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 10, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **kwargs: int) -> None:
        self.current += timedelta(**kwargs)


def _context(adapter: str, user: str, request: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, request_id=request, operation_id=operation_id)


async def _enter_cultivator(runtime, adapter: str, user: str) -> None:
    for index, command in enumerate(
        ("开始修仙", "寻仙问道", "完成引导 阅读", "前往近郊", "完成引导 采集", "完成引导 炼丹", "选择道途 体修")
    ):
        result = await runtime.adapters.dispatch(adapter, _context(adapter, user, f"setup-{index}"), command)
        assert result.ok, (command, result.code, result.message)


def _copy_data(tmp_path: Path) -> Path:
    data_root = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_root)
    return data_root


def _configure_cultivation_snapshot_case(data_root: Path) -> None:
    path, document = _cultivation_document(data_root)
    breathing = next(row for row in document["records"] if row["key"] == "cultivate.breathing")
    breathing.update({"energy_cost": 2, "soul_power_gain": 7, "soul_power_max": 300})
    _write_document(path, document)


def _duplicate_json_member(raw: str, key: str, original: int, replacement: int) -> str:
    member = f'{json.dumps(key)}: {original}'
    assert raw.count(member) == 1
    return raw.replace(member, f'{member}, {json.dumps(key)}: {replacement}', 1)


def _cultivation_state(runtime, adapter: str, user: str, session_id: str, operation_id: str):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player = connection.execute(
            "SELECT id, cultivation, total_cultivation, soul_power, soul_power_max, stamina, energy "
            "FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()
        assert player is not None
        session = connection.execute(
            "SELECT status, ends_at, stamina_cost, snapshot_json, result_json, updated_at "
            "FROM cultivation_sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        operation = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        operation_count = connection.execute(
            "SELECT COUNT(*) FROM operations WHERE player_id=?", (player[0],)
        ).fetchone()[0]
    return player, session, operation, operation_count


def _cultivation_integrity_state(
    runtime, adapter: str, user: str, operation_ids: tuple[str, ...]
):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player = connection.execute(
            "SELECT id, cultivation, total_cultivation, soul_power, soul_power_max, stamina, energy, "
            "qualification_json, item_effects_json FROM players "
            "WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()
        assert player is not None
        sessions = connection.execute(
            "SELECT session_id, status, ends_at, stamina_cost, snapshot_json, result_json, updated_at "
            "FROM cultivation_sessions WHERE player_id=? ORDER BY id",
            (player[0],),
        ).fetchall()
        operations = tuple(
            connection.execute(
                "SELECT operation_name, player_id, request_hash, result_json "
                "FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            for operation_id in operation_ids
        )
        operation_count = connection.execute(
            "SELECT COUNT(*) FROM operations WHERE player_id=?", (player[0],)
        ).fetchone()[0]
    return player, sessions, operations, operation_count


def _cultivation_document(data_root: Path) -> tuple[Path, dict]:
    path = data_root / "养成" / "修炼.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


def test_cultivation_content_keeps_only_rule_inputs() -> None:
    path = Path(__file__).parents[1] / "data" / "养成" / "修炼.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    assert all("desc" not in row for row in document["records"])
    assert set(CULTIVATION_GUIDANCE) == {row["key"] for row in document["records"]}
    assert all(CULTIVATION_GUIDANCE[key] for key in CULTIVATION_GUIDANCE)
    assert set(cultivation_definitions()) == set(CULTIVATION_GUIDANCE)


def test_progression_unlocks_and_qualifications_are_read_from_content(tmp_path: Path) -> None:
    data_root = _copy_data(tmp_path)
    path = data_root / "境界" / "晋升.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    guidance = next(row for row in document["records"] if row["key"] == "guidance.path")
    guidance.update(name="山门指引", desc="可向山门长者请教本门心法。")
    foundation = next(
        row for row in document["records"] if row["key"] == "milestone.foundation_late"
    )
    foundation["required_total_cultivation"] = 12345
    _write_document(path, document)

    content = ContentBundle.load(data_root)
    layer_unlock = next(
        unlock for unlock in layer_unlocks("qi_sensing", 3, content) if unlock.key == "guidance.path"
    )
    milestone = next(
        definition
        for definition in milestone_definitions(content)
        if definition.key == "milestone.foundation_late"
    )

    assert (layer_unlock.title, layer_unlock.description) == (
        "山门指引",
        "可向山门长者请教本门心法。",
    )
    assert milestone.required_total_cultivation == 12345
    assert len(progression_unlock_definitions(content)) == 11


@pytest.mark.parametrize(
    ("key", "field", "value", "error"),
    (
        ("guidance.path", "realm_key", "realm.missing", "unknown active realm"),
        ("milestone.foundation_late", "required_total_cultivation", True, "non-negative integer"),
        ("milestone.foundation_late", "required_layer", 0, "outside foundation"),
        ("milestone.foundation_late", "unlock_status", "locked", "unsupported unlock_status"),
        ("guidance.path", "status", None, "unsupported status"),
        ("guidance.path", "trigger", [], "unsupported trigger"),
    ),
)
def test_progression_unlock_content_rejects_invalid_fields(
    tmp_path: Path,
    key: str,
    field: str,
    value: object,
    error: str,
) -> None:
    data_root = _copy_data(tmp_path)
    path = data_root / "境界" / "晋升.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    next(row for row in document["records"] if row["key"] == key)[field] = value
    _write_document(path, document)

    with pytest.raises(ContentError, match=error):
        progression_unlock_definitions(ContentBundle.load(data_root))


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_progression_content_changes_apply_to_new_advances_but_replay_is_frozen(
    tmp_path: Path,
    adapter: str,
) -> None:
    async def run(data_root: Path) -> None:
        path = data_root / "境界" / "晋升.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        foundation = next(
            row for row in document["records"] if row["key"] == "milestone.foundation_late"
        )
        foundation.update(
            name="根基圆成",
            desc="根基稳固，可继续探访云舟与深层洞天。",
            required_total_cultivation=12345,
        )
        _write_document(path, document)

        runtime = create_runtime(data_dir=data_root)
        user = f"progression-content-{adapter}"
        await _enter_cultivator(runtime, adapter, user)
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute(
                "UPDATE players SET realm_key='foundation', realm_layer=8, cultivation=6300, "
                "total_cultivation=12345 WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            )
        first = await runtime.adapters.dispatch(
            adapter,
            _context(adapter, user, "advance", operation_id="foundation-advance"),
            "晋升境界",
        )
        assert first.code == "REALM_LAYER_ADVANCED"
        assert first.data["unlocks"] == [
            {
                "key": "milestone.foundation_late",
                "title": "根基圆成",
                "description": "根基稳固，可继续探访云舟与深层洞天。",
                "status": "open",
            }
        ]
        await runtime.close()

        foundation.update(
            name="新名",
            desc="只影响新晋层的内容。",
            required_total_cultivation=12346,
        )
        _write_document(path, document)
        runtime = create_runtime(data_dir=data_root)
        replay = await runtime.adapters.dispatch(
            adapter,
            _context(adapter, user, "advance-replay", operation_id="foundation-advance"),
            "晋升境界",
        )
        assert replay.data["idempotent_replay"] is True
        assert replay.data["unlocks"] == first.data["unlocks"]

        next_user = f"progression-content-new-{adapter}"
        await _enter_cultivator(runtime, adapter, next_user)
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute(
                "UPDATE players SET realm_key='foundation', realm_layer=8, cultivation=6300, "
                "total_cultivation=12345 WHERE platform=? AND platform_user_id=?",
                (adapter, next_user),
            )
        below_new_threshold = await runtime.adapters.dispatch(
            adapter,
            _context(adapter, next_user, "new-threshold"),
            "晋升境界",
        )
        assert below_new_threshold.code == "REALM_LAYER_ADVANCED"
        assert below_new_threshold.data["unlocks"] == []
        await runtime.close()

        foundation["status"] = "closed"
        _write_document(path, document)
        runtime = create_runtime(data_dir=data_root)
        closed_replay = await runtime.adapters.dispatch(
            adapter,
            _context(adapter, user, "closed-replay", operation_id="foundation-advance"),
            "晋升境界",
        )
        assert closed_replay.data["idempotent_replay"] is True
        assert closed_replay.data["unlocks"] == first.data["unlocks"]

        closed_user = f"progression-content-closed-{adapter}"
        await _enter_cultivator(runtime, adapter, closed_user)
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute(
                "UPDATE players SET realm_key='foundation', realm_layer=8, cultivation=6300, "
                "total_cultivation=99999 WHERE platform=? AND platform_user_id=?",
                (adapter, closed_user),
            )
        closed_advance = await runtime.adapters.dispatch(
            adapter,
            _context(adapter, closed_user, "closed-advance"),
            "晋升境界",
        )
        assert closed_advance.code == "REALM_LAYER_ADVANCED"
        assert closed_advance.data["unlocks"] == []
        await runtime.close()

    asyncio.run(run(_copy_data(tmp_path)))


def _write_document(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")


def test_cultivation_parameters_and_history_are_frozen_across_content_change(tmp_path: Path) -> None:
    async def run(data_root: Path) -> None:
        path, document = _cultivation_document(data_root)
        breathing = next(row for row in document["records"] if row["key"] == "cultivate.breathing")
        breathing.update({"stamina_cost": 4, "duration_seconds": 1200, "base_cultivation": 123})
        _write_document(path, document)

        clock = MutableClock()
        runtime = create_runtime(data_dir=data_root, clock=clock)
        user = "content-freeze"
        await _enter_cultivator(runtime, "qq.official", user)
        started = await runtime.adapters.dispatch(
            "qq.official",
            _context("qq.official", user, "start", operation_id="cultivation-start"),
            "开始修炼 调息",
        )
        assert started.code == "CULTIVATION_STARTED"
        assert started.data["stamina_cost"] == 4
        assert started.data["ends_at"]
        with sqlite3.connect(runtime.settings.database_path) as connection:
            snapshot = json.loads(
                connection.execute(
                    "SELECT snapshot_json FROM cultivation_sessions WHERE session_id = ?",
                    (started.data["session_id"],),
                ).fetchone()[0]
            )
        clock.advance(minutes=20, seconds=1)

        path, document = _cultivation_document(data_root)
        breathing = next(row for row in document["records"] if row["key"] == "cultivate.breathing")
        breathing.update({"name": "静息吐纳", "aliases": [], "stamina_cost": 9, "duration_seconds": 60, "base_cultivation": 9999})
        _write_document(path, document)
        await runtime.close()
        runtime = create_runtime(data_dir=data_root, clock=clock)
        replay = await runtime.adapters.dispatch(
            "qq.official",
            _context("qq.official", user, "start-replay", operation_id="cultivation-start"),
            "开始修炼 调息",
        )
        assert replay.ok
        assert replay.data["idempotent_replay"] is True
        assert replay.data["mode_label"] == "调息修炼"

        settled = await runtime.adapters.dispatch(
            "qq.official",
            _context("qq.official", user, "settle", operation_id="cultivation-settle"),
            "结算修炼",
        )
        assert settled.code == "CULTIVATION_SETTLED"
        assert settled.data["mode_key"] == "cultivate.breathing"
        assert settled.data["cultivation_gain"] == cultivation_gain(
            snapshot["base_cultivation"],
            snapshot["qualification"],
            environment_bp=snapshot["environment_bp"],
            state_bp=snapshot["state_bp"],
            manual_bonus_bp=snapshot["manual_cultivation_gain_bp"],
        )
        await runtime.close()

    with TemporaryDirectory() as directory:
        asyncio.run(run(_copy_data(Path(directory))))


def test_closed_cultivation_mode_rejects_new_session_without_changing_state(tmp_path: Path) -> None:
    async def run(data_root: Path) -> None:
        path, document = _cultivation_document(data_root)
        next(row for row in document["records"] if row["key"] == "cultivate.spirit_spring")["status"] = "closed"
        _write_document(path, document)
        runtime = create_runtime(data_dir=data_root)
        user = "closed-cultivation"
        await _enter_cultivator(runtime, "onebot.v11", user)
        with sqlite3.connect(runtime.settings.database_path) as connection:
            before = connection.execute(
                "SELECT stamina, energy FROM players WHERE platform = ? AND platform_user_id = ?",
                ("onebot.v11", user),
            ).fetchone()
        result = await runtime.adapters.dispatch(
            "onebot.v11", _context("onebot.v11", user, "closed"), "开始修炼 灵泉"
        )
        assert result.code == "INVALID_CULTIVATION_MODE"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute(
                "SELECT stamina, energy FROM players WHERE platform = ? AND platform_user_id = ?",
                ("onebot.v11", user),
            ).fetchone() == before
            assert connection.execute("SELECT COUNT(*) FROM cultivation_sessions").fetchone()[0] == 0
        await runtime.close()

    asyncio.run(run(_copy_data(tmp_path)))


def test_cultivation_location_copy_uses_current_content_names(tmp_path: Path) -> None:
    async def run(data_root: Path) -> None:
        mode_path, mode_document = _cultivation_document(data_root)
        spring = next(row for row in mode_document["records"] if row["key"] == "cultivate.spirit_spring")
        spring.update({"name": "清心泉修炼", "aliases": ["清心泉"]})
        _write_document(mode_path, mode_document)
        location_path = data_root / "地图" / "地点.json"
        location_document = json.loads(location_path.read_text(encoding="utf-8"))
        next(row for row in location_document["records"] if row["key"] == "xuantian.spirit_field")["name"] = "清心泉谷"
        _write_document(location_path, location_document)

        runtime = create_runtime(data_dir=data_root)
        user = "dynamic-cultivation-copy"
        await _enter_cultivator(runtime, "qq.official", user)
        result = await runtime.adapters.dispatch(
            "qq.official", _context("qq.official", user, "location-copy"), "开始修炼 清心泉"
        )
        assert result.code == "LOCATION_REQUIRED"
        assert "清心泉修炼" in result.message
        assert "清心泉谷" in result.message
        await runtime.close()

    asyncio.run(run(_copy_data(tmp_path)))


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_cultivation_operation_bad_json_is_read_only_and_both_adapters_share_flow(tmp_path: Path, adapter: str) -> None:
    async def run(data_root: Path) -> None:
        runtime = create_runtime(data_dir=data_root)
        user = f"bad-operation-{adapter}"
        await _enter_cultivator(runtime, adapter, user)
        operation_id = f"bad-start-{adapter}"
        started = await runtime.adapters.dispatch(
            adapter, _context(adapter, user, "start", operation_id=operation_id), "开始修炼"
        )
        assert started.ok
        with sqlite3.connect(runtime.settings.database_path) as connection:
            before = connection.execute(
                "SELECT stamina, energy FROM players WHERE platform = ? AND platform_user_id = ?",
                (adapter, user),
            ).fetchone()
            connection.execute("UPDATE operations SET result_json = ? WHERE operation_id = ?", ("{", operation_id))
        replay = await runtime.adapters.dispatch(
            adapter, _context(adapter, user, "start-replay", operation_id=operation_id), "开始修炼"
        )
        assert replay.code == "PERSISTENCE_ERROR"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute(
                "SELECT stamina, energy FROM players WHERE platform = ? AND platform_user_id = ?",
                (adapter, user),
            ).fetchone() == before
            assert connection.execute("SELECT COUNT(*) FROM cultivation_sessions").fetchone()[0] == 1
        await runtime.close()

    asyncio.run(run(_copy_data(tmp_path)))


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_cultivation_settlement_rejects_tampered_snapshot_and_operation_replay(
    tmp_path: Path, adapter: str
) -> None:
    async def run(data_root: Path) -> None:
        _configure_cultivation_snapshot_case(data_root)
        clock = MutableClock()
        runtime = create_runtime(data_dir=data_root, clock=clock)
        user = f"settlement-snapshot-{adapter}"
        settle_operation_id = f"settle-snapshot-{adapter}"
        try:
            await _enter_cultivator(runtime, adapter, user)
            started = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "start", operation_id=f"start-settlement-{adapter}"),
                "开始修炼 调息",
            )
            assert started.code == "CULTIVATION_STARTED"
            session_id = started.data["session_id"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                original_snapshot = connection.execute(
                    "SELECT snapshot_json FROM cultivation_sessions WHERE session_id=?",
                    (session_id,),
                ).fetchone()[0]
            clock.advance(minutes=11)
            snapshot = json.loads(original_snapshot)

            duplicate_snapshot = _duplicate_json_member(
                original_snapshot,
                "base_cultivation",
                snapshot["base_cultivation"],
                snapshot["base_cultivation"] + 999,
            )
            for corrupted_snapshot in (duplicate_snapshot,):
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE cultivation_sessions SET snapshot_json=? WHERE session_id=?",
                        (corrupted_snapshot, session_id),
                    )
                before = _cultivation_state(
                    runtime, adapter, user, session_id, settle_operation_id
                )
                rejected = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "duplicate-settlement", operation_id=settle_operation_id),
                    "结算修炼",
                )
                assert rejected.code == "PERSISTENCE_ERROR"
                assert _cultivation_state(
                    runtime, adapter, user, session_id, settle_operation_id
                ) == before

            semantic_snapshot = dict(snapshot)
            semantic_snapshot["base_cultivation"] += 999
            semantic_snapshot["soul_power_gain"] += 100
            changed_snapshot = json.dumps(semantic_snapshot, ensure_ascii=False, sort_keys=True)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE cultivation_sessions SET snapshot_json=? WHERE session_id=?",
                    (changed_snapshot, session_id),
                )
            before_semantic_change = _cultivation_state(
                runtime, adapter, user, session_id, settle_operation_id
            )
            semantic_rejection = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "semantic-settlement", operation_id=settle_operation_id),
                "结算修炼",
            )
            assert semantic_rejection.code == "PERSISTENCE_ERROR"
            assert _cultivation_state(
                runtime, adapter, user, session_id, settle_operation_id
            ) == before_semantic_change

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE cultivation_sessions SET snapshot_json=? WHERE session_id=?",
                    (original_snapshot, session_id),
                )
            settled = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "settle", operation_id=settle_operation_id),
                "结算修炼",
            )
            assert settled.code == "CULTIVATION_SETTLED"
            assert settled.data["cultivation_gain"] > 0
            assert settled.data["soul_power_gain"] == snapshot["soul_power_gain"]
            await runtime.close()

            runtime = create_runtime(data_dir=data_root, clock=clock)
            before_replay = _cultivation_state(
                runtime, adapter, user, session_id, settle_operation_id
            )
            replay = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "settle-replay", operation_id=settle_operation_id),
                "结算修炼",
            )
            assert replay.code == "CULTIVATION_SETTLED"
            assert replay.data["idempotent_replay"] is True
            assert _cultivation_state(
                runtime, adapter, user, session_id, settle_operation_id
            ) == before_replay

            with sqlite3.connect(runtime.settings.database_path) as connection:
                operation_result = connection.execute(
                    "SELECT result_json FROM operations WHERE operation_id=?",
                    (settle_operation_id,),
                ).fetchone()[0]
                operation_payload = json.loads(operation_result)
                altered_player = dict(operation_payload["player"])
                altered_player["cultivation"] += 999
                altered_payload = dict(operation_payload, player=altered_player)
                connection.execute(
                    "UPDATE operations SET result_json=? WHERE operation_id=?",
                    (
                        json.dumps(altered_payload, ensure_ascii=False, sort_keys=True),
                        settle_operation_id,
                    ),
                )
            before_altered_player = _cultivation_state(
                runtime, adapter, user, session_id, settle_operation_id
            )
            altered_player_replay = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "altered-player-replay", operation_id=settle_operation_id),
                "结算修炼",
            )
            assert altered_player_replay.code == "PERSISTENCE_ERROR"
            assert _cultivation_state(
                runtime, adapter, user, session_id, settle_operation_id
            ) == before_altered_player
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE operations SET result_json=? WHERE operation_id=?",
                    (operation_result, settle_operation_id),
                )
                gain = json.loads(operation_result)["cultivation_gain"]
                connection.execute(
                    "UPDATE operations SET result_json=? WHERE operation_id=?",
                    (
                        _duplicate_json_member(
                            operation_result, "cultivation_gain", gain, gain + 999
                        ),
                        settle_operation_id,
                    ),
                )
            before_bad_replay = _cultivation_state(
                runtime, adapter, user, session_id, settle_operation_id
            )
            bad_replay = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "duplicate-result-replay", operation_id=settle_operation_id),
                "结算修炼",
            )
            assert bad_replay.code == "PERSISTENCE_ERROR"
            assert _cultivation_state(
                runtime, adapter, user, session_id, settle_operation_id
            ) == before_bad_replay
        finally:
            await runtime.close()

    asyncio.run(run(_copy_data(tmp_path)))


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_expired_cultivation_recovery_rejects_tampering_and_keeps_recovery_lock(
    tmp_path: Path, adapter: str
) -> None:
    async def run(data_root: Path) -> None:
        _configure_cultivation_snapshot_case(data_root)
        clock = MutableClock()
        runtime = create_runtime(data_dir=data_root, clock=clock)
        user = f"recovery-snapshot-{adapter}"
        recovery_operation_id = f"recover-snapshot-{adapter}"
        try:
            await _enter_cultivator(runtime, adapter, user)
            started = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "start", operation_id=f"start-recovery-{adapter}"),
                "开始修炼 调息",
            )
            assert started.code == "CULTIVATION_STARTED"
            session_id = started.data["session_id"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                original_snapshot = connection.execute(
                    "SELECT snapshot_json FROM cultivation_sessions WHERE session_id=?",
                    (session_id,),
                ).fetchone()[0]
            clock.advance(days=2, minutes=11)
            snapshot = json.loads(original_snapshot)
            duplicate_snapshot = _duplicate_json_member(
                original_snapshot,
                "base_cultivation",
                snapshot["base_cultivation"],
                snapshot["base_cultivation"] + 999,
            )
            semantic_snapshot = dict(snapshot)
            semantic_snapshot["base_cultivation"] += 999
            semantic_snapshot["soul_power_gain"] += 100
            changed_snapshot = json.dumps(semantic_snapshot, ensure_ascii=False, sort_keys=True)
            expire_operation_id = f"expire-recovery-{adapter}"
            for index, corrupted_snapshot in enumerate((duplicate_snapshot, changed_snapshot)):
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE cultivation_sessions SET snapshot_json=? WHERE session_id=?",
                        (corrupted_snapshot, session_id),
                    )
                before_expiry_rejection = _cultivation_state(
                    runtime, adapter, user, session_id, expire_operation_id
                )
                expiry_rejection = await runtime.adapters.dispatch(
                    adapter,
                    _context(
                        adapter,
                        user,
                        f"corrupt-expiry-{index}",
                        operation_id=expire_operation_id,
                    ),
                    "结算修炼",
                )
                assert expiry_rejection.code == "PERSISTENCE_ERROR"
                assert _cultivation_state(
                    runtime, adapter, user, session_id, expire_operation_id
                ) == before_expiry_rejection

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE cultivation_sessions SET snapshot_json=? WHERE session_id=?",
                    (original_snapshot, session_id),
                )
            expired = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "expire", operation_id=expire_operation_id),
                "结算修炼",
            )
            assert expired.code == "CULTIVATION_EXPIRED"

            for index, corrupted_snapshot in enumerate((duplicate_snapshot, changed_snapshot)):
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE cultivation_sessions SET snapshot_json=? WHERE session_id=?",
                        (corrupted_snapshot, session_id),
                    )
                before_recovery_rejection = _cultivation_state(
                    runtime, adapter, user, session_id, recovery_operation_id
                )
                recovery_rejection = await runtime.adapters.dispatch(
                    adapter,
                    _context(
                        adapter,
                        user,
                        f"corrupt-recovery-{index}",
                        operation_id=recovery_operation_id,
                    ),
                    "恢复修炼",
                )
                assert recovery_rejection.code == "PERSISTENCE_ERROR"
                assert _cultivation_state(
                    runtime, adapter, user, session_id, recovery_operation_id
                ) == before_recovery_rejection

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE cultivation_sessions SET snapshot_json=? WHERE session_id=?",
                    (original_snapshot, session_id),
                )
            recovered = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "recover", operation_id=recovery_operation_id),
                "恢复修炼",
            )
            assert recovered.code == "CULTIVATION_RECOVERED"
            assert recovered.data["cultivation_gain"] > 0
            await runtime.close()

            runtime = create_runtime(data_dir=data_root, clock=clock)
            before_replay = _cultivation_state(
                runtime, adapter, user, session_id, recovery_operation_id
            )
            replay = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "recover-replay", operation_id=recovery_operation_id),
                "恢复修炼",
            )
            assert replay.code == "CULTIVATION_RECOVERED"
            assert replay.data["idempotent_replay"] is True
            assert _cultivation_state(
                runtime, adapter, user, session_id, recovery_operation_id
            ) == before_replay

            with sqlite3.connect(runtime.settings.database_path) as connection:
                session_result = connection.execute(
                    "SELECT result_json FROM cultivation_sessions WHERE session_id=?",
                    (session_id,),
                ).fetchone()[0]
                gain = json.loads(session_result)["cultivation_gain"]
                connection.execute(
                    "UPDATE cultivation_sessions SET result_json=? WHERE session_id=?",
                    (
                        _duplicate_json_member(session_result, "cultivation_gain", gain, 0),
                        session_id,
                    ),
                )
            lock_operation_id = f"recover-lock-check-{adapter}"
            before_lock_check = _cultivation_state(
                runtime, adapter, user, session_id, lock_operation_id
            )
            locked = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "duplicate-expired-result", operation_id=lock_operation_id),
                "恢复修炼",
            )
            assert locked.code == "PERSISTENCE_ERROR"
            assert _cultivation_state(
                runtime, adapter, user, session_id, lock_operation_id
            ) == before_lock_check
        finally:
            await runtime.close()

    asyncio.run(run(_copy_data(tmp_path)))


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_cultivation_cancel_rejects_tampered_snapshot_and_replays_once(
    tmp_path: Path, adapter: str
) -> None:
    async def run(data_root: Path) -> None:
        _configure_cultivation_snapshot_case(data_root)
        clock = MutableClock()
        runtime = create_runtime(data_dir=data_root, clock=clock)
        user = f"cancel-snapshot-{adapter}"
        cancel_operation_id = f"cancel-snapshot-{adapter}"
        try:
            await _enter_cultivator(runtime, adapter, user)
            started = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "start", operation_id=f"start-cancel-{adapter}"),
                "开始修炼 调息",
            )
            assert started.code == "CULTIVATION_STARTED"
            session_id = started.data["session_id"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                original_snapshot = connection.execute(
                    "SELECT snapshot_json FROM cultivation_sessions WHERE session_id=?",
                    (session_id,),
                ).fetchone()[0]
            snapshot = json.loads(original_snapshot)
            duplicate_snapshot = _duplicate_json_member(
                original_snapshot,
                "energy_cost",
                snapshot["energy_cost"],
                snapshot["energy_cost"] + 999,
            )
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE cultivation_sessions SET snapshot_json=? WHERE session_id=?",
                    (duplicate_snapshot, session_id),
                )
            before_duplicate = _cultivation_state(
                runtime, adapter, user, session_id, cancel_operation_id
            )
            duplicate_rejection = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "duplicate-cancel", operation_id=cancel_operation_id),
                "取消修炼",
            )
            assert duplicate_rejection.code == "PERSISTENCE_ERROR"
            assert _cultivation_state(
                runtime, adapter, user, session_id, cancel_operation_id
            ) == before_duplicate

            semantic_snapshot = dict(snapshot)
            semantic_snapshot["energy_cost"] += 999
            changed_snapshot = json.dumps(semantic_snapshot, ensure_ascii=False, sort_keys=True)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE cultivation_sessions SET snapshot_json=? WHERE session_id=?",
                    (changed_snapshot, session_id),
                )
            before_semantic_change = _cultivation_state(
                runtime, adapter, user, session_id, cancel_operation_id
            )
            semantic_rejection = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "semantic-cancel", operation_id=cancel_operation_id),
                "取消修炼",
            )
            assert semantic_rejection.code == "PERSISTENCE_ERROR"
            assert _cultivation_state(
                runtime, adapter, user, session_id, cancel_operation_id
            ) == before_semantic_change

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE cultivation_sessions SET snapshot_json=? WHERE session_id=?",
                    (original_snapshot, session_id),
                )
            cancelled = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "cancel", operation_id=cancel_operation_id),
                "取消修炼",
            )
            assert cancelled.code == "CULTIVATION_CANCELLED"
            assert cancelled.data["energy_refund"] == snapshot["energy_cost"]
            await runtime.close()

            runtime = create_runtime(data_dir=data_root, clock=clock)
            before_replay = _cultivation_state(
                runtime, adapter, user, session_id, cancel_operation_id
            )
            replay = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "cancel-replay", operation_id=cancel_operation_id),
                "取消修炼",
            )
            assert replay.code == "CULTIVATION_CANCELLED"
            assert replay.data["idempotent_replay"] is True
            assert _cultivation_state(
                runtime, adapter, user, session_id, cancel_operation_id
            ) == before_replay
        finally:
            await runtime.close()

    asyncio.run(run(_copy_data(tmp_path)))


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_cultivation_start_replay_rejects_tampered_player_view(
    tmp_path: Path, adapter: str
) -> None:
    async def run(data_root: Path) -> None:
        runtime = create_runtime(data_dir=data_root)
        user = f"start-replay-snapshot-{adapter}"
        operation_id = f"start-replay-snapshot-{adapter}"
        try:
            await _enter_cultivator(runtime, adapter, user)
            started = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "start", operation_id=operation_id),
                "开始修炼 调息",
            )
            assert started.code == "CULTIVATION_STARTED"
            session_id = started.data["session_id"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                raw_result = connection.execute(
                    "SELECT result_json FROM operations WHERE operation_id=?", (operation_id,)
                ).fetchone()[0]
                payload = json.loads(raw_result)
                player = dict(payload["player"])
                player["cultivation"] += 1
                connection.execute(
                    "UPDATE operations SET result_json=? WHERE operation_id=?",
                    (json.dumps(dict(payload, player=player), ensure_ascii=False, sort_keys=True), operation_id),
                )
            before = _cultivation_state(runtime, adapter, user, session_id, operation_id)
            replay = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "start-replay", operation_id=operation_id),
                "开始修炼 调息",
            )
            assert replay.code == "PERSISTENCE_ERROR"
            assert _cultivation_state(runtime, adapter, user, session_id, operation_id) == before
        finally:
            await runtime.close()

    asyncio.run(run(_copy_data(tmp_path)))


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_cultivation_snapshot_schema_rejects_invalid_values_without_side_effects(
    tmp_path: Path, adapter: str
) -> None:
    async def run(data_root: Path) -> None:
        _configure_cultivation_snapshot_case(data_root)
        clock = MutableClock()
        runtime = create_runtime(data_dir=data_root, clock=clock)
        user = f"snapshot-schema-{adapter}"
        start_operation_id = f"start-schema-{adapter}"
        settle_operation_id = f"settle-schema-{adapter}"
        try:
            await _enter_cultivator(runtime, adapter, user)
            started = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "start", operation_id=start_operation_id),
                "开始修炼 调息",
            )
            assert started.code == "CULTIVATION_STARTED"
            session_id = started.data["session_id"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                original_snapshot = connection.execute(
                    "SELECT snapshot_json FROM cultivation_sessions WHERE session_id=?",
                    (session_id,),
                ).fetchone()[0]
                original_start_result = connection.execute(
                    "SELECT result_json FROM operations WHERE operation_id=?",
                    (start_operation_id,),
                ).fetchone()[0]

            cases: list[tuple[str, str, object]] = [
                ("missing-base-cultivation", "base_cultivation", None)
            ]
            positive_integer_fields = (
                "realm_layer",
                "duration_seconds",
                "stamina_cost",
                "state_bp",
                "base_cultivation",
                "environment_bp",
            )
            for field in positive_integer_fields:
                for label, value in (
                    ("bool", True),
                    ("float", 1.0),
                    ("string", "1"),
                    ("negative", -1),
                ):
                    cases.append((f"{field}-{label}", field, value))
            for field in (
                "energy_cost",
                "state_bonus_bp",
                "pending_state_bonus_bp",
                "manual_cultivation_gain_bp",
                "soul_power_gain",
                "soul_power_max",
            ):
                cases.append((f"{field}-negative", field, -1))
            for label, value in (("bool", True), ("float", 1.0), ("negative", -1)):
                cases.append((f"qualification-{label}", f"qualification.body", value))
            for field in ("realm_key", "location_key", "mode_key", "mode_label"):
                cases.extend(((f"{field}-non-string", field, True), (f"{field}-empty", field, "")))

            original_start = json.loads(original_start_result)
            for label, field, invalid_value in cases:
                snapshot = json.loads(original_snapshot)
                if label == "missing-base-cultivation":
                    del snapshot[field]
                elif field.startswith("qualification."):
                    snapshot["qualification"][field.split(".", 1)[1]] = invalid_value
                else:
                    snapshot[field] = invalid_value

                start_result = dict(original_start)
                start_result["snapshot_fingerprint"] = runtime.repository._request_hash(
                    "progression.cultivation.snapshot", snapshot
                )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE cultivation_sessions SET snapshot_json=? WHERE session_id=?",
                        (json.dumps(snapshot, ensure_ascii=False, sort_keys=True), session_id),
                    )
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (
                            json.dumps(start_result, ensure_ascii=False, sort_keys=True),
                            start_operation_id,
                        ),
                    )

                before = _cultivation_state(
                    runtime, adapter, user, session_id, settle_operation_id
                )
                rejected = await runtime.adapters.dispatch(
                    adapter,
                    _context(
                        adapter,
                        user,
                        f"invalid-snapshot-{label}",
                        operation_id=settle_operation_id,
                    ),
                    "结算修炼",
                )
                assert rejected.code == "PERSISTENCE_ERROR", label
                assert _cultivation_state(
                    runtime, adapter, user, session_id, settle_operation_id
                ) == before, label

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE cultivation_sessions SET snapshot_json=? WHERE session_id=?",
                        (original_snapshot, session_id),
                    )
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (original_start_result, start_operation_id),
                    )

            clock.advance(minutes=11)
            settled = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "settle-valid", operation_id=settle_operation_id),
                "结算修炼",
            )
            assert settled.code == "CULTIVATION_SETTLED"
            assert settled.data["cultivation_gain"] > 0
        finally:
            await runtime.close()

    asyncio.run(run(_copy_data(tmp_path)))


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_cultivation_start_rejects_invalid_player_qualification_without_side_effects(
    tmp_path: Path, adapter: str
) -> None:
    async def run(data_root: Path) -> None:
        runtime = create_runtime(data_dir=data_root)
        user = f"invalid-cultivation-qualification-{adapter}"
        operation_id = f"start-invalid-qualification-{adapter}"
        try:
            await _enter_cultivator(runtime, adapter, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id, original_qualification = connection.execute(
                    "SELECT id, qualification_json FROM players "
                    "WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
            valid_qualification = json.loads(original_qualification)
            invalid_qualifications = []
            missing_field = dict(valid_qualification)
            del missing_field["body"]
            invalid_qualifications.append(("missing-field", missing_field))
            negative_value = dict(valid_qualification)
            negative_value["body"] = -1
            invalid_qualifications.append(("negative-value", negative_value))

            for label, qualification in invalid_qualifications:
                invalid_json = json.dumps(qualification, ensure_ascii=False, sort_keys=True)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET qualification_json=? WHERE id=?",
                        (invalid_json, player_id),
                    )
                before = _cultivation_integrity_state(
                    runtime, adapter, user, (operation_id,)
                )
                rejected = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"invalid-qualification-{label}", operation_id=operation_id),
                    "开始修炼 调息",
                )
                assert rejected.code == "PERSISTENCE_ERROR", label
                assert _cultivation_integrity_state(
                    runtime, adapter, user, (operation_id,)
                ) == before, label

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET qualification_json=? WHERE id=?",
                    (original_qualification, player_id),
                )
            started = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "valid-qualification", operation_id=operation_id),
                "开始修炼 调息",
            )
            assert started.code == "CULTIVATION_STARTED"
        finally:
            await runtime.close()

    asyncio.run(run(_copy_data(tmp_path)))


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_cultivation_terminal_rejects_tampered_start_request_hash_without_writes(
    tmp_path: Path, adapter: str
) -> None:
    async def run(data_root: Path) -> None:
        _configure_cultivation_snapshot_case(data_root)
        clock = MutableClock()
        runtime = create_runtime(data_dir=data_root, clock=clock)
        user = f"start-request-hash-{adapter}"
        try:
            await _enter_cultivator(runtime, adapter, user)
            paths = (
                ("settle", "结算修炼", "CULTIVATION_SETTLED"),
                ("cancel", "取消修炼", "CULTIVATION_CANCELLED"),
                ("recover", "恢复修炼", "CULTIVATION_RECOVERED"),
            )
            for path, command, success_code in paths:
                start_operation_id = f"start-request-hash-{path}-{adapter}"
                terminal_operation_id = f"terminal-request-hash-{path}-{adapter}"
                started = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"start-{path}", operation_id=start_operation_id),
                    "开始修炼 调息",
                )
                assert started.code == "CULTIVATION_STARTED"
                if path == "settle":
                    clock.advance(minutes=11)
                elif path == "recover":
                    clock.advance(days=2)

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    original_request_hash = connection.execute(
                        "SELECT request_hash FROM operations WHERE operation_id=?",
                        (start_operation_id,),
                    ).fetchone()[0]
                    tampered_request_hash = "0" * 64
                    if original_request_hash == tampered_request_hash:
                        tampered_request_hash = "1" * 64
                    connection.execute(
                        "UPDATE operations SET request_hash=? WHERE operation_id=?",
                        (tampered_request_hash, start_operation_id),
                    )

                operation_ids = (start_operation_id, terminal_operation_id)
                before = _cultivation_integrity_state(
                    runtime, adapter, user, operation_ids
                )
                rejected = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"reject-{path}", operation_id=terminal_operation_id),
                    command,
                )
                assert rejected.code == "PERSISTENCE_ERROR", path
                assert _cultivation_integrity_state(
                    runtime, adapter, user, operation_ids
                ) == before, path

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE operations SET request_hash=? WHERE operation_id=?",
                        (original_request_hash, start_operation_id),
                    )
                completed = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"retry-{path}", operation_id=terminal_operation_id),
                    command,
                )
                assert completed.code == success_code, path
        finally:
            await runtime.close()

    asyncio.run(run(_copy_data(tmp_path)))


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_cultivation_start_replay_validates_terminal_operation_ledger(
    tmp_path: Path, adapter: str
) -> None:
    async def run(data_root: Path) -> None:
        _configure_cultivation_snapshot_case(data_root)
        clock = MutableClock()
        runtime = create_runtime(data_dir=data_root, clock=clock)
        user = f"terminal-ledger-replay-{adapter}"
        try:
            await _enter_cultivator(runtime, adapter, user)
            paths = (
                ("settle", "结算修炼", "CULTIVATION_SETTLED"),
                ("cancel", "取消修炼", "CULTIVATION_CANCELLED"),
                ("recover", "恢复修炼", "CULTIVATION_RECOVERED"),
            )
            for path, command, success_code in paths:
                start_operation_id = f"start-terminal-ledger-{path}-{adapter}"
                terminal_operation_id = f"terminal-ledger-{path}-{adapter}"
                started = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"start-{path}", operation_id=start_operation_id),
                    "开始修炼 调息",
                )
                assert started.code == "CULTIVATION_STARTED"
                if path == "settle":
                    clock.advance(minutes=11)
                elif path == "recover":
                    clock.advance(days=2)
                completed = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"finish-{path}", operation_id=terminal_operation_id),
                    command,
                )
                assert completed.code == success_code, path
                session_id = started.data["session_id"]
                baseline_replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"baseline-replay-{path}", operation_id=start_operation_id),
                    "开始修炼 调息",
                )
                assert baseline_replay.code == "CULTIVATION_STARTED", path
                assert baseline_replay.data["idempotent_replay"] is True, path
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    original_session_result = connection.execute(
                        "SELECT result_json FROM cultivation_sessions WHERE session_id=?",
                        (session_id,),
                    ).fetchone()[0]
                    original_terminal_operation = connection.execute(
                        "SELECT request_hash, result_json FROM operations WHERE operation_id=?",
                        (terminal_operation_id,),
                    ).fetchone()
                original_terminal_request_hash = original_terminal_operation[0]
                original_terminal_result = original_terminal_operation[1]

                session_result = json.loads(original_session_result)
                session_result["operation_result_fingerprint"] = (
                    "0" * 64
                    if session_result["operation_result_fingerprint"] != "0" * 64
                    else "1" * 64
                )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE cultivation_sessions SET result_json=? WHERE session_id=?",
                        (
                            json.dumps(session_result, ensure_ascii=False, sort_keys=True),
                            session_id,
                        ),
                    )
                operation_ids = (start_operation_id, terminal_operation_id)
                before_fingerprint_replay = _cultivation_integrity_state(
                    runtime, adapter, user, operation_ids
                )
                bad_fingerprint_replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"bad-fingerprint-{path}", operation_id=start_operation_id),
                    "开始修炼 调息",
                )
                assert bad_fingerprint_replay.code == "PERSISTENCE_ERROR", path
                assert _cultivation_integrity_state(
                    runtime, adapter, user, operation_ids
                ) == before_fingerprint_replay, path

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE cultivation_sessions SET result_json=? WHERE session_id=?",
                        (original_session_result, session_id),
                    )
                    operation_payload = json.loads(original_terminal_result)
                    damaged_value = (
                        "stamina_refund" if path == "cancel" else "cultivation_gain"
                    )
                    operation_payload[damaged_value] += 1
                    damaged_terminal_result = json.dumps(
                        operation_payload, ensure_ascii=False, sort_keys=True
                    )
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (damaged_terminal_result, terminal_operation_id),
                    )
                before_result_replay = _cultivation_integrity_state(
                    runtime, adapter, user, operation_ids
                )
                bad_result_replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"bad-result-{path}", operation_id=start_operation_id),
                    "开始修炼 调息",
                )
                assert bad_result_replay.code == "PERSISTENCE_ERROR", path
                assert _cultivation_integrity_state(
                    runtime, adapter, user, operation_ids
                ) == before_result_replay, path

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (original_terminal_result, terminal_operation_id),
                    )
                    damaged_request_hash = "0" * 64
                    if original_terminal_request_hash == damaged_request_hash:
                        damaged_request_hash = "1" * 64
                    connection.execute(
                        "UPDATE operations SET request_hash=? WHERE operation_id=?",
                        (damaged_request_hash, terminal_operation_id),
                    )
                before_request_hash_replay = _cultivation_integrity_state(
                    runtime, adapter, user, operation_ids
                )
                bad_request_hash_replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(
                        adapter,
                        user,
                        f"bad-terminal-request-hash-{path}",
                        operation_id=start_operation_id,
                    ),
                    "开始修炼 调息",
                )
                assert bad_request_hash_replay.code == "PERSISTENCE_ERROR", path
                assert _cultivation_integrity_state(
                    runtime, adapter, user, operation_ids
                ) == before_request_hash_replay, path

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE operations SET request_hash=? WHERE operation_id=?",
                        (original_terminal_request_hash, terminal_operation_id),
                    )
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"replay-{path}", operation_id=start_operation_id),
                    "开始修炼 调息",
                )
                assert replay.code == "CULTIVATION_STARTED", path
                assert replay.data["idempotent_replay"] is True, path
        finally:
            await runtime.close()

    asyncio.run(run(_copy_data(tmp_path)))


def test_cultivation_content_rejects_duplicate_player_references(tmp_path: Path) -> None:
    data_root = _copy_data(tmp_path)
    path, document = _cultivation_document(data_root)
    next(row for row in document["records"] if row["key"] == "cultivate.seclusion")["aliases"] = ["调息"]
    _write_document(path, document)
    with pytest.raises(ContentError, match="duplicate cultivation name or alias"):
        cultivation_definitions(ContentBundle.load(data_root))
