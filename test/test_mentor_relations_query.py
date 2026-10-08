from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(adapter: str, user: str, request_id: str, *, writable: bool) -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request_id,
        can_write_assets=writable,
    )


async def _dispatch(runtime, adapter: str, user: str, request_id: str, command: str, *, writable: bool = True):
    return await runtime.adapters.dispatch(
        adapter,
        _context(adapter, user, request_id, writable=writable),
        command,
    )


async def _create_player(runtime, adapter: str, user: str, dao_name: str) -> None:
    created = await _dispatch(runtime, adapter, user, f"{user}-create", "开始修仙")
    assert created.code == "PLAYER_CREATED", created
    renamed = await _dispatch(runtime, adapter, user, f"{user}-rename", f"修仙改名 {dao_name}")
    assert renamed.code == "DAO_NAME_CHANGED", renamed
    seeking = await _dispatch(runtime, adapter, user, f"{user}-seek", "寻仙问道")
    assert seeking.code == "SEEKING_STARTED", seeking


def _set_realm(runtime, adapter: str, user: str, realm: str, layer: int, *, stage: str | None = None) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        if stage is None:
            connection.execute(
                "UPDATE players SET realm_key=?, realm_layer=? WHERE platform=? AND platform_user_id=?",
                (realm, layer, adapter, user),
            )
        else:
            connection.execute(
                "UPDATE players SET stage=?, realm_key=?, realm_layer=? WHERE platform=? AND platform_user_id=?",
                (stage, realm, layer, adapter, user),
            )


def _database_dump(runtime) -> tuple[str, ...]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return tuple(connection.iterdump())


def _relation_rows(runtime, adapter: str, master: str) -> list[tuple[str, str, str]]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return connection.execute(
            """
            SELECT r.relation_id, r.status, r.created_at
            FROM mentor_relations r
            JOIN players p ON p.id = r.master_id
            WHERE p.platform=? AND p.platform_user_id=?
            ORDER BY r.created_at DESC, r.relation_id DESC
            """,
            (adapter, master),
        ).fetchall()


async def _prepare_five_states(runtime, adapter: str, clock: MutableClock) -> dict[str, str]:
    names = {
        "master": "玄衡",
        "rejected": "青萝",
        "active": "白芷",
        "graduated": "云岫",
        "expired": "沉璧",
        "invited": "素问",
    }
    for user, dao_name in names.items():
        await _create_player(runtime, adapter, user, dao_name)
    _set_realm(runtime, adapter, "master", "foundation", 4)

    invited = await _dispatch(runtime, adapter, "master", "invite-rejected", "邀请拜师 rejected")
    assert invited.code == "MENTOR_INVITED", invited
    rejected = await _dispatch(
        runtime,
        adapter,
        "rejected",
        "reject-rejected",
        f"拒绝拜师 {invited.data['relation_id']}",
    )
    assert rejected.code == "MENTOR_REJECTED", rejected

    invited = await _dispatch(runtime, adapter, "master", "invite-active", "邀请拜师 active")
    assert invited.code == "MENTOR_INVITED", invited
    accepted = await _dispatch(
        runtime,
        adapter,
        "active",
        "accept-active",
        f"接受拜师 {invited.data['relation_id']}",
    )
    assert accepted.code == "MENTOR_ACCEPTED", accepted
    active_relation_id = accepted.data["relation_id"]

    invited = await _dispatch(runtime, adapter, "master", "invite-graduated", "邀请拜师 graduated")
    assert invited.code == "MENTOR_INVITED", invited
    relation_id = invited.data["relation_id"]
    accepted = await _dispatch(
        runtime,
        adapter,
        "graduated",
        "accept-graduated",
        f"接受拜师 {relation_id}",
    )
    assert accepted.code == "MENTOR_ACCEPTED", accepted
    _set_realm(runtime, adapter, "graduated", "qi_gathering", 3, stage="cultivator")
    with sqlite3.connect(runtime.settings.database_path) as connection:
        apprentice_id = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, "graduated"),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO production_orders(
                order_id, player_id, operation_id, recipe_key, status,
                starts_at, ends_at, energy_cost, currency_cost,
                snapshot_json, result_json, created_at, updated_at
            ) VALUES (?, ?, ?, 'recipe.pill.healing_low', 'completed',
                      '2026-09-23T00:00:00+00:00', '2026-09-23T00:01:00+00:00',
                      0, 0, '{}', '{}', '2026-09-23T00:00:00+00:00', '2026-09-23T00:01:00+00:00')
            """,
            (f"mentor-query-production-{adapter}", apprentice_id, f"mentor-query-production-op-{adapter}"),
        )
    graduated = await _dispatch(runtime, adapter, "master", "graduate", f"师徒毕业 {relation_id}")
    assert graduated.code == "MENTOR_GRADUATED", graduated

    # Keep two pending invitations so the expired one can be projected without
    # issuing another write that would materialize all due invitations.
    invited = await _dispatch(runtime, adapter, "master", "invite-expired", "邀请拜师 expired")
    assert invited.code == "MENTOR_INVITED", invited
    expired_relation_id = invited.data["relation_id"]
    clock.advance(hours=23)
    invited = await _dispatch(runtime, adapter, "master", "invite-pending", "邀请拜师 invited")
    assert invited.code == "MENTOR_INVITED", invited
    clock.advance(hours=2)
    return {
        "rejected": rejected.data["relation_id"],
        "active": active_relation_id,
        "graduated": relation_id,
        "expired": expired_relation_id,
        "invited": invited.data["relation_id"],
    }


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_mentor_relations_query_returns_empty_without_writes(adapter: str, tmp_path) -> None:
    async def run() -> None:
        runtime = create_runtime(data_dir=tmp_path / f"empty-{adapter.replace('.', '-')}", adapters=(adapter,))
        try:
            await _create_player(runtime, adapter, "solo", "独行")
            before = _database_dump(runtime)
            result = await _dispatch(runtime, adapter, "solo", "mentor-query-empty", "师徒关系", writable=False)
            assert result.ok, result
            assert result.code == "MENTOR_NONE"
            assert result.data == {"status": "none", "relations": [], "count": 0}
            assert result.operation_id is None
            assert _database_dump(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_mentor_relations_query_projects_five_states_and_stable_fields(adapter: str, tmp_path) -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 10, 9, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=tmp_path / adapter.replace(".", "-"), clock=clock, adapters=(adapter,))
        try:
            relation_ids = await _prepare_five_states(runtime, adapter, clock)
            before = _database_dump(runtime)
            result = await _dispatch(runtime, adapter, "master", "mentor-query", "师徒关系", writable=False)
            assert result.ok, result
            assert result.code == "MENTOR_RELATIONS"
            assert result.operation_id is None
            assert result.data["count"] == 5
            rows = result.data["relations"]
            assert len(rows) == 5
            expected_order = [row[0] for row in _relation_rows(runtime, adapter, "master")]
            assert [row["relation_id"] for row in rows] == expected_order
            assert {row["status"] for row in rows} == {"invited", "active", "graduated", "rejected", "expired"}
            by_id = {row["relation_id"]: row for row in rows}
            assert by_id[relation_ids["invited"]]["status"] == "invited"
            assert by_id[relation_ids["expired"]]["status"] == "expired"
            assert by_id[relation_ids["graduated"]]["status"] == "graduated"
            assert by_id[relation_ids["active"]]["status"] == "active"
            assert by_id[relation_ids["rejected"]]["status"] == "rejected"

            expected_keys = {
                "relation_id",
                "status",
                "role",
                "counterpart_dao_name",
                "master_dao_name",
                "apprentice_dao_name",
                "invited_at",
                "expires_at",
                "accepted_at",
                "rejected_at",
                "graduated_at",
                "master_contribution",
            }
            for row in rows:
                assert set(row) == expected_keys
                assert row["role"] == "master"
                assert row["master_dao_name"] == "玄衡"
                assert row["counterpart_dao_name"] in {"青萝", "白芷", "云岫", "沉璧", "素问"}
                assert "platform_user_id" not in row
                assert "player_id" not in row
            graduated_row = by_id[relation_ids["graduated"]]
            expired_row = by_id[relation_ids["expired"]]
            assert graduated_row["counterpart_dao_name"] == "云岫"
            assert graduated_row["master_contribution"] == 20
            assert graduated_row["accepted_at"] is not None
            assert graduated_row["graduated_at"] is not None
            assert expired_row["accepted_at"] is None
            assert expired_row["graduated_at"] is None
            assert _database_dump(runtime) == before

            before_apprentice = _database_dump(runtime)
            apprentice_result = await _dispatch(
                runtime,
                adapter,
                "active",
                "mentor-query-apprentice",
                "我的师徒",
                writable=False,
            )
            assert apprentice_result.code == "MENTOR_RELATIONS"
            assert apprentice_result.data["count"] == 1
            apprentice_row = apprentice_result.data["relations"][0]
            assert apprentice_row["role"] == "apprentice"
            assert apprentice_row["counterpart_dao_name"] == "玄衡"
            assert apprentice_row["master_dao_name"] == "玄衡"
            assert apprentice_row["apprentice_dao_name"] == "白芷"
            assert _database_dump(runtime) == before_apprentice
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_mentor_relations_query_expiry_is_projection_only(adapter: str, tmp_path) -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 10, 9, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=tmp_path / f"expiry-{adapter.replace('.', '-')}", clock=clock, adapters=(adapter,))
        try:
            await _create_player(runtime, adapter, "master", "玄衡")
            await _create_player(runtime, adapter, "apprentice", "白芷")
            _set_realm(runtime, adapter, "master", "foundation", 4)
            invitation = await _dispatch(runtime, adapter, "master", "invite", "邀请拜师 apprentice")
            relation_id = invitation.data["relation_id"]
            clock.advance(hours=25)
            before = _database_dump(runtime)
            result = await _dispatch(runtime, adapter, "master", "query-expired", "师门关系", writable=False)
            assert result.code == "MENTOR_RELATIONS"
            assert result.data["relations"][0]["status"] == "expired"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                status = connection.execute(
                    "SELECT status FROM mentor_relations WHERE relation_id=?", (relation_id,)
                ).fetchone()[0]
                operation_count = connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_name LIKE 'social.%mentor%'"
                ).fetchone()[0]
            assert status == "invited"
            assert operation_count == 1
            assert _database_dump(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("column,value", (("expires_at", "not-a-time"), ("status", "active")))
@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_mentor_relations_query_rejects_malformed_rows_without_writes(
    adapter: str, column: str, value: str, tmp_path
) -> None:
    async def run() -> None:
        runtime = create_runtime(data_dir=tmp_path / f"malformed-{adapter.replace('.', '-')}-{column}", adapters=(adapter,))
        try:
            await _create_player(runtime, adapter, "master", "玄衡")
            await _create_player(runtime, adapter, "apprentice", "白芷")
            _set_realm(runtime, adapter, "master", "foundation", 4)
            invitation = await _dispatch(runtime, adapter, "master", "invite", "邀请拜师 apprentice")
            relation_id = invitation.data["relation_id"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    f"UPDATE mentor_relations SET {column}=? WHERE relation_id=?",
                    (value, relation_id),
                )
            before = _database_dump(runtime)
            result = await _dispatch(runtime, adapter, "master", "query-malformed", "师徒关系", writable=False)
            assert not result.ok
            assert result.code == "PERSISTENCE_ERROR"
            assert result.retryable is True
            assert _database_dump(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())
