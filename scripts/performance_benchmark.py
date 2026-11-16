"""Bounded SQLite/application performance benchmark.

The benchmark owns a temporary database and never touches the repository's
``data/`` directory.  Use ``XIUXIAN_PERF_USERS=1000000`` (the default) for the
release-scale run; smaller values are useful for a quick smoke check.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import resource
import shutil
import sqlite3
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nonebot_plugin_xiuxian_3.adapters.message.markdown import command_targets, markdown_to_text
from nonebot_plugin_xiuxian_3.adapters.message.qq import qq_command_link, qq_keyboard
from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event as normalize_onebot_event
from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event
from nonebot_plugin_xiuxian_3.runtime import create_runtime


PLAYER_INSERT = """
INSERT INTO players(
    id, player_id, platform, platform_user_id, scene_id, nickname, dao_name,
    stage, status, location_key, qualification_json, spirit_stones, stamina,
    stamina_max, energy, energy_max, inventory_json, intro_json, realm_key,
    realm_layer, cultivation, total_cultivation, max_hp, max_mp,
    carry_capacity, exploration_efficiency_bp, initiative, faction_reputation_json,
    durability_json, item_effects_json, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, '', 'cultivator', 'active', ?, ?, 50, 80, 100,
          20, 30, ?, ?, 'golden_core', 1, 1000, 1000, 10000, 1000,
          60, 10000, 100, '{}', '{}', '{}', ?, ?)
"""
MAINLINE_INSERT = """
INSERT INTO mainline_runs(
    player_id, story_key, chapter, stage, stage_key, status, attempt_count,
    first_clear_claimed, first_clear_key, snapshot_json, result_json,
    created_at, updated_at
) VALUES (?, 'story.mainline.xuantian', 1, 1, 'chapter.1.stage.1',
          'claimed', 1, 1, ?, '{}', '{}', ?, ?)
"""
IDLE_INSERT = """
INSERT INTO idle_assignments(
    assignment_id, player_id, operation_id, route_key, status, business_date,
    starts_at, claim_at, max_claim_at, cancel_until, cost_json, snapshot_json,
    result_json, created_at, updated_at
) VALUES (?, ?, ?, 'idle.herb_vale_gather', 'running', '2026-11-15',
          '2026-11-15T00:00:00+00:00', '2026-11-16T00:00:00+00:00',
          '2026-11-17T00:00:00+00:00', '2026-11-15T01:00:00+00:00',
          '{"stamina": 8, "energy": 2}',
          '{"label": "百草坡采药"}', '{}', ?, ?)
"""


@dataclass(frozen=True, slots=True)
class Percentiles:
    count: int
    p50_ms: float
    p95_ms: float
    p99_ms: float


@dataclass(frozen=True, slots=True)
class LevelResult:
    concurrency: int
    requests: int
    errors: int
    latency_ms: Percentiles
    serialization_ms: Percentiles
    cpu_seconds: float
    max_rss_mb: float
    command_latency_ms: dict[str, Percentiles]
    command_errors: dict[str, int]
    stage_latency_ms: dict[str, Percentiles]
    inflight_wait_ms: Percentiles
    connection_open_ms: Percentiles
    sql_queries: int | None


class _TimedSemaphore(asyncio.Semaphore):
    """Optional measurement of application admission wait time."""

    def __init__(self, value: int, samples: list[float]):
        super().__init__(value)
        self._samples = samples

    async def acquire(self) -> bool:
        started = time.perf_counter()
        acquired = await super().acquire()
        self._samples.append((time.perf_counter() - started) * 1000)
        return acquired


def _instrument_repository(runtime: Any, *, enabled: bool | None = None) -> dict[str, list[float]] | None:
    profile_enabled = enabled if enabled is not None else os.getenv("XIUXIAN_PERF_PROFILE") == "1"
    if not profile_enabled:
        return None
    metrics: dict[str, list[float]] = {
        "inflight_wait_ms": [],
        "connection_open_ms": [],
        "player_profile_ms": [],
        "idle_status_ms": [],
        "mainline_status_ms": [],
        "travel_preview_ms": [],
        "sql_queries": [],
    }
    repository = runtime.repository
    repository._inflight = _TimedSemaphore(runtime.settings.max_inflight, metrics["inflight_wait_ms"])

    def timed_method(name: str, metric: str) -> None:
        original = getattr(repository, name)

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                metrics[metric].append((time.perf_counter() - started) * 1000)

        setattr(repository, name, wrapped)

    timed_method("_get_player_profile_sync", "player_profile_ms")
    timed_method("_get_idle_status_once", "idle_status_ms")
    timed_method("_get_mainline_status_sync", "mainline_status_ms")
    timed_method("_preview_travel_database_state", "travel_preview_ms")
    original_connect = repository._connect

    def timed_connect() -> sqlite3.Connection:
        started = time.perf_counter()
        try:
            connection = original_connect()
            connection.set_trace_callback(
                lambda statement: metrics["sql_queries"].append(1.0)
                if not statement.lstrip().upper().startswith("PRAGMA")
                else None
            )
            return connection
        finally:
            metrics["connection_open_ms"].append((time.perf_counter() - started) * 1000)

    repository._connect = timed_connect
    return metrics


def _percentiles(values: Iterable[float]) -> Percentiles:
    ordered = sorted(values)
    if not ordered:
        return Percentiles(0, 0.0, 0.0, 0.0)

    def pick(fraction: float) -> float:
        index = min(len(ordered) - 1, max(0, int((len(ordered) * fraction + 0.999999) - 1)))
        return round(ordered[index], 3)

    return Percentiles(len(ordered), pick(0.50), pick(0.95), pick(0.99))


def _rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 3)


def _db_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.parent.glob(path.name + "*") if item.exists())


def _seed_database(runtime: Any, users: int, batch_size: int) -> dict[str, float | int]:
    started = time.perf_counter()
    now = "2026-11-15T00:00:00+00:00"
    path = runtime.settings.database_path
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("BEGIN")
        for first in range(0, users, batch_size):
            last = min(users, first + batch_size)
            players = []
            mainline = []
            idle = []
            for number in range(first, last):
                platform = "onebot.v11" if number % 2 == 0 else "qq.official"
                user_id = f"perf-{number:07d}"
                player_id = number + 1
                players.append(
                    (
                        player_id,
                        f"perf-player-{number:07d}",
                        platform,
                        user_id,
                        f"group:perf-{number % 1000:04d}",
                        "性能道友",
                        "xuantian.herb_vale",
                        "{\"body\":10,\"fortune\":10,\"insight\":10,\"root\":10,\"spirit\":10,\"agility\":10}",
                        "{}",
                        "{}",
                        now,
                        now,
                    )
                )
                mainline.append((player_id, f"perf-mainline-{number:07d}", now, now))
                idle.append((f"perf-idle-{number:07d}", player_id, f"perf-idle-op-{number:07d}", now, now))
            connection.executemany(PLAYER_INSERT, players)
            connection.executemany(MAINLINE_INSERT, mainline)
            connection.executemany(IDLE_INSERT, idle)
        connection.execute(
            "INSERT INTO sects(sect_id,name,name_key,leader_id,status,level,max_members,warehouse_capacity,construction,spirit_stones,sect_merit,warehouse_json,created_at,updated_at) "
            "VALUES ('perf-sect','性能宗门','perf-sect',1,'active',1,?,0,0,0,0,'{}',?,?)",
            (users, now, now),
        )
        connection.execute(
            "INSERT INTO domain_front_rounds(round_id,activity_id,location_key,status,activity_starts_at,activity_ends_at,starts_at,ends_at,claim_expires_at,target_quantity,rules_snapshot_json,total_contribution,result_json,created_at,updated_at) "
            "VALUES ('perf-round','perf-activity','xuantian.domain_front','settled',?,?,?,?,?,1,'{}',0,'{}',?,?)",
            (now, now, now, now, now, now, now),
        )
        domain_participants = []
        domain_contributions = []
        domain_claims = []
        for number in range(users):
            player_id = number + 1
            domain_participants.append(
                ('perf-round', player_id, 'perf-sect', 'domain.fire', 0, 1, 'active', '{}', now)
            )
            domain_contributions.append(
                ('perf-round', player_id, 'perf-sect', 'domain.fire', f'perf-source-{number:07d}', 'point', 1, f'perf-domain-op-{number:07d}', now)
            )
            domain_claims.append(
                ('perf-round', player_id, f'perf-domain-claim-{number:07d}', '{}', now)
            )
        connection.executemany(
            "INSERT INTO domain_front_participants(round_id,player_id,sect_id,domain_key,stamina_cost,contribution,status,snapshot_json,joined_at) VALUES (?,?,?,?,?,?,?,?,?)",
            domain_participants,
        )
        connection.executemany(
            "INSERT INTO domain_front_contributions(round_id,player_id,sect_id,domain_key,source_operation_id,action_key,quantity,operation_id,occurred_at) VALUES (?,?,?,?,?,?,?,?,?)",
            domain_contributions,
        )
        connection.executemany(
            "INSERT INTO domain_front_claims(round_id,player_id,operation_id,reward_json,claimed_at) VALUES (?,?,?,?,?)",
            domain_claims,
        )
        connection.commit()
        connection.execute("PRAGMA synchronous=NORMAL")
    return {
        "users": users,
        "domain_front_rows": users,
        "seed_seconds": round(time.perf_counter() - started, 3),
        "db_bytes": _db_size(path),
    }


def _onebot_event(user_id: str, request_number: int, text: str) -> Any:
    return SimpleNamespace(
        post_type="message",
        message_type="group",
        user_id=user_id,
        group_id="perf-group",
        message_id=f"perf-ob-{request_number}",
        self_id="perf-bot",
        raw_message=text,
        sender={"nickname": "性能道友", "user_id": user_id},
    )


def _qq_event(user_id: str, request_number: int, text: str) -> Any:
    return SimpleNamespace(
        id=f"perf-qq-{request_number}",
        content=text,
        group_openid="perf-group",
        author={"member_openid": user_id, "username": "性能道友"},
    )


def _normalize(adapter: str, user_id: str, request_number: int, text: str) -> Any:
    if adapter == "onebot.v11":
        return normalize_onebot_event(_onebot_event(user_id, request_number, text))
    return normalize_qq_event(_qq_event(user_id, request_number, text), bot_id="perf-bot")


def _serialize_response(adapter: str, result: Any) -> float:
    started = time.perf_counter()
    json.dumps(result.data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    markdown_to_text(result.message)
    command_targets(result.message)
    if adapter == "qq.official":
        for action in result.actions:
            qq_command_link(action.label, action.command)
        if result.actions:
            qq_keyboard((tuple((action.label, action.command) for action in result.actions),))
    return (time.perf_counter() - started) * 1000


async def _request(runtime: Any, adapter: str, user_id: str, request_number: int, text: str) -> tuple[float, float, bool]:
    started = time.perf_counter()
    try:
        normalized = _normalize(adapter, user_id, request_number, text)
        result = await runtime.adapters.dispatch(adapter, normalized.context, normalized.text)
        serialization_ms = _serialize_response(adapter, result)
        return (time.perf_counter() - started) * 1000, serialization_ms, not result.ok
    except Exception:
        return (time.perf_counter() - started) * 1000, 0.0, True


async def _measure(
    runtime: Any,
    users: int,
    concurrency: int,
    total_requests: int,
    metrics: dict[str, list[float]] | None = None,
    commands: tuple[str, ...] | None = None,
) -> LevelResult:
    # Keep each level's request population stable so concurrency is the only
    # variable in the comparison.
    adapters = ("onebot.v11", "qq.official")
    commands = commands or ("我的状态", "挂机状态", "主线状态", "移动预览 玄天近郊")
    samples = tuple(
        (adapters[number % 2], f"perf-{number % users:07d}", commands[number % len(commands)])
        for number in range(total_requests)
    )
    latency: list[float] = []
    serialization: list[float] = []
    latency_by_command: dict[str, list[float]] = {command: [] for command in commands}
    errors_by_command: dict[str, int] = {command: 0 for command in commands}
    errors = 0
    if metrics is not None:
        for values in metrics.values():
            values.clear()
    before_cpu = resource.getrusage(resource.RUSAGE_SELF)
    cursor = 0
    while cursor < len(samples):
        batch = samples[cursor : cursor + concurrency]
        values = await asyncio.gather(
            *(_request(runtime, adapter, user_id, cursor + offset, command) for offset, (adapter, user_id, command) in enumerate(batch))
        )
        for offset, (request_latency, response_serialization, failed) in enumerate(values):
            latency.append(request_latency)
            serialization.append(response_serialization)
            errors += int(failed)
            command = batch[offset][2]
            latency_by_command[command].append(request_latency)
            errors_by_command[command] += int(failed)
        cursor += len(batch)
    after_cpu = resource.getrusage(resource.RUSAGE_SELF)
    cpu_seconds = (after_cpu.ru_utime + after_cpu.ru_stime) - (before_cpu.ru_utime + before_cpu.ru_stime)
    return LevelResult(
        concurrency=concurrency,
        requests=len(samples),
        errors=errors,
        latency_ms=_percentiles(latency),
        serialization_ms=_percentiles(serialization),
        cpu_seconds=round(cpu_seconds, 3),
        max_rss_mb=_rss_mb(),
        command_latency_ms={command: _percentiles(values) for command, values in latency_by_command.items()},
        command_errors=errors_by_command,
        stage_latency_ms={
            key.removesuffix("_ms"): _percentiles(values)
            for key, values in (metrics or {}).items()
            if key not in {"inflight_wait_ms", "connection_open_ms", "sql_queries"}
        },
        inflight_wait_ms=_percentiles((metrics or {}).get("inflight_wait_ms", ())),
        connection_open_ms=_percentiles((metrics or {}).get("connection_open_ms", ())),
        sql_queries=(len(metrics["sql_queries"]) if metrics is not None else None),
    )


def _explain(path: Path, player_id: int) -> dict[str, list[str]]:
    queries = {
        "player_lookup": "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
        "idle_status": "SELECT * FROM idle_assignments WHERE player_id = ? AND status = 'running' ORDER BY id DESC LIMIT 1",
        "mainline_progress": "SELECT * FROM mainline_runs WHERE player_id = ? AND story_key = ?",
        "mainline_evidence": """
            SELECT ? AS event_key
            WHERE EXISTS (
                SELECT 1 FROM town_commission_claims
                WHERE player_id = ? AND status = 'delivered'
            )
            UNION ALL
            SELECT ? AS event_key
            WHERE EXISTS (
                SELECT 1 FROM domain_front_participants WHERE player_id = ?
            )
            UNION ALL
            SELECT ? AS event_key
            WHERE EXISTS (
                SELECT 1
                FROM domain_front_battle_links AS links
                JOIN battle_sessions AS sessions
                  ON sessions.battle_id = links.battle_id
                WHERE links.player_id = ?
                  AND sessions.player_id = links.player_id
                  AND sessions.battle_type = 'pve.domain_front'
                  AND sessions.status = 'settled'
                  AND json_extract(sessions.result_json, '$.outcome') = 'won'
            )
            UNION ALL
            SELECT ? AS event_key
            WHERE EXISTS (SELECT 1 FROM domain_front_contributions WHERE player_id = ?)
            UNION ALL
            SELECT ? AS event_key
            WHERE EXISTS (
                SELECT 1 FROM domain_front_claims WHERE player_id = ?
            )
            UNION ALL
            SELECT ? AS event_key
            WHERE EXISTS (
                SELECT 1 FROM void_archive_unlocks
                WHERE player_id = ? AND event_key = ? AND ends_at > ?
            )
            UNION ALL
            SELECT ? AS event_key
            WHERE EXISTS (
                SELECT 1 FROM void_archive_runs
                WHERE player_id = ? AND outcome = 'won'
            )
            UNION ALL
            SELECT ? AS event_key
            WHERE EXISTS (
                SELECT 1 FROM time_fort_members
                WHERE player_id = ? AND status = 'settled' AND first_clear = 1
            )
            UNION ALL
            SELECT 'livelihood.project.' || p.project_key || '.completed' AS event_key
            FROM livelihood_project_rewards AS r
            JOIN livelihood_projects AS p ON p.project_id = r.project_id
            WHERE r.player_id = ? AND r.eligible = 1
        """,
        "location_quest_progress": "SELECT quest_key FROM quest_progress WHERE player_id = ? AND status IN ('completed', 'claimed')",
        "location_mentor_relation": "SELECT 1 FROM mentor_relations WHERE apprentice_id = ? AND (status='active' OR (status='invited' AND expires_at>?)) LIMIT 1",
        "location_requirement_state": """
            SELECT quest_key AS value, 0 AS mentor
            FROM quest_progress
            WHERE player_id = ? AND status IN ('completed', 'claimed')
            UNION ALL
            SELECT NULL AS value,
                   EXISTS(
                       SELECT 1
                       FROM mentor_relations
                       WHERE apprentice_id = ?
                         AND (status = 'active' OR (status = 'invited' AND expires_at > ?))
                       LIMIT 1
                   ) AS mentor
        """,
        "location_daily_travel": "SELECT COUNT(*) AS count FROM travel_sessions WHERE player_id = ? AND destination = ? AND starts_at >= ? AND starts_at < ?",
    }
    params = {
        "player_lookup": ("onebot.v11", f"perf-{player_id - 1:07d}"),
        "idle_status": (player_id,),
        "mainline_progress": (player_id, "story.mainline.xuantian"),
        "mainline_evidence": (
            "event.town_commission.delivered", player_id,
            "event.domain_front.joined", player_id,
            "event.domain_front.battle", player_id,
            "event.domain_front.contribution", player_id,
            "event.domain_front.claimed", player_id,
            "event.archive_unlock", player_id, "event.archive_unlock", "2026-11-15T00:00:00+00:00",
            "event.archive_guard.won", player_id,
            "story.mainline.void_archive.time_fort", player_id,
            player_id,
        ),
        "location_quest_progress": (player_id,),
        "location_mentor_relation": (player_id, "2026-11-15T00:00:00+00:00"),
        "location_requirement_state": (player_id, player_id, "2026-11-15T00:00:00+00:00"),
        "location_daily_travel": (player_id, "xuantian.suburb", "2026-11-15T00:00:00+00:00", "2026-11-16T00:00:00+00:00"),
    }
    with sqlite3.connect(path) as connection:
        return {
            key: [str(row[3]) for row in connection.execute("EXPLAIN QUERY PLAN " + query, params[key]).fetchall()]
            for key, query in queries.items()
        }


async def _run(
    users: int,
    batch_size: int,
    total_requests: int,
    levels: tuple[int, ...],
    *,
    drop_domain_front_indexes: bool = False,
    profile_sql: bool | None = None,
    commands: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    temporary_path: Path
    with tempfile.TemporaryDirectory(prefix="xiuxian-perf-") as data_dir:
        temporary_path = Path(data_dir)
        runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11", "qq.official"))
        await runtime.initialize()
        seed = _seed_database(runtime, users, batch_size)
        if drop_domain_front_indexes:
            with sqlite3.connect(runtime.settings.database_path) as connection:
                for index in (
                    "idx_domain_front_participants_player",
                    "idx_domain_front_contributions_player",
                    "idx_domain_front_claims_player",
                ):
                    connection.execute(f"DROP INDEX IF EXISTS {index}")
        explain = _explain(runtime.settings.database_path, 1)
        metrics = _instrument_repository(runtime, enabled=profile_sql)
        results = [
            asdict(await _measure(runtime, users, concurrency, total_requests, metrics, commands))
            for concurrency in levels
        ]
        await runtime.close()
        db_bytes = _db_size(runtime.settings.database_path)
        payload = {
            "users": users,
            "seed": seed,
            "database_bytes_after_benchmark": db_bytes,
            "sql_profile_enabled": metrics is not None,
            "sql_profile_status": "collected" if metrics is not None else "not_collected",
            "explain_query_plan": explain,
            "levels": results,
            "errors": sum(int(item["errors"]) for item in results),
        }
    payload["temporary_database_cleaned"] = not temporary_path.exists()
    return payload


def _connection_probe_wrapper(connect: Any, enabled: bool) -> Any:
    if not enabled:
        return connect

    def probed(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = connect(*args, **kwargs)
        connection.execute("SELECT 1")
        return connection

    return probed


async def _run_connection_probe_comparison(
    users: int,
    batch_size: int,
    total_requests: int,
    levels: tuple[int, ...],
    *,
    profile_sql: bool | None = None,
    commands: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Compare the removed per-request probe without reseeding the fixture."""

    temporary_path: Path
    with tempfile.TemporaryDirectory(prefix="xiuxian-perf-") as data_dir:
        temporary_path = Path(data_dir)
        runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11", "qq.official"))
        await runtime.initialize()
        seed = _seed_database(runtime, users, batch_size)
        explain = _explain(runtime.settings.database_path, 1)
        metrics = _instrument_repository(runtime, enabled=profile_sql)
        traced_connect = runtime.repository._connect

        async def measure(probe: bool) -> list[dict[str, Any]]:
            runtime.repository._connect = _connection_probe_wrapper(traced_connect, probe)
            return [
                asdict(await _measure(runtime, users, concurrency, total_requests, metrics, commands))
                for concurrency in levels
            ]

        before_results = await measure(True)
        after_results = await measure(False)
        await runtime.close()
        db_bytes = _db_size(runtime.settings.database_path)

        def report(results: list[dict[str, Any]]) -> dict[str, Any]:
            return {
                "users": users,
                "seed": seed,
                "database_bytes_after_benchmark": db_bytes,
                "sql_profile_enabled": metrics is not None,
                "sql_profile_status": "collected" if metrics is not None else "not_collected",
                "explain_query_plan": explain,
                "levels": results,
                "errors": sum(int(item["errors"]) for item in results),
            }

        payload = {
            "comparison": {
                "before_with_connection_probe": report(before_results),
                "after_without_connection_probe": report(after_results),
            },
            "errors": sum(
                int(item["errors"])
                for results in (before_results, after_results)
                for item in results
            ),
        }
    cleaned = not temporary_path.exists()
    for result in payload["comparison"].values():
        result["temporary_database_cleaned"] = cleaned
    return payload


async def _run_manual_catalogue_comparison(
    users: int,
    batch_size: int,
    total_requests: int,
    levels: tuple[int, ...],
    *,
    profile_sql: bool | None = None,
    commands: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Compare manual-only catalogue iteration without reseeding the fixture."""

    from nonebot_plugin_xiuxian_3.xiuxian.content import bundled_content
    from nonebot_plugin_xiuxian_3.xiuxian.items import manual_rules

    temporary_path: Path
    with tempfile.TemporaryDirectory(prefix="xiuxian-perf-") as data_dir:
        temporary_path = Path(data_dir)
        runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11", "qq.official"))
        await runtime.initialize()
        seed = _seed_database(runtime, users, batch_size)
        explain = _explain(runtime.settings.database_path, 1)
        metrics = _instrument_repository(runtime, enabled=profile_sql)
        optimized_item_records = manual_rules._item_records
        legacy_cache: list[tuple[int, Any, tuple[dict[str, object], ...]]] = []

        def legacy_item_records(bundle: Any) -> tuple[dict[str, object], ...]:
            bundle_id = id(bundle)
            for cached_id, cached_bundle, records in reversed(legacy_cache):
                if cached_id == bundle_id and cached_bundle is bundle:
                    return records
            records = tuple(bundle.list("item", include_locked=False))
            legacy_cache[:] = [
                item for item in legacy_cache
                if not (item[0] == bundle_id and item[1] is bundle)
            ]
            legacy_cache.append((bundle_id, bundle, records))
            if len(legacy_cache) > 16:
                del legacy_cache[:-16]
            return records

        async def measure(item_records: Any) -> list[dict[str, Any]]:
            manual_rules._item_records = item_records
            manual_rules._ITEM_RECORD_CACHE.clear()
            return [
                asdict(await _measure(runtime, users, concurrency, total_requests, metrics, commands))
                for concurrency in levels
            ]

        try:
            before_results = await measure(legacy_item_records)
            after_results = await measure(optimized_item_records)
        finally:
            manual_rules._item_records = optimized_item_records
            manual_rules._ITEM_RECORD_CACHE.clear()
        await runtime.close()
        db_bytes = _db_size(runtime.settings.database_path)

        def report(results: list[dict[str, Any]], records: tuple[dict[str, object], ...]) -> dict[str, Any]:
            return {
                "users": users,
                "seed": seed,
                "database_bytes_after_benchmark": db_bytes,
                "catalogue_records": len(records),
                "sql_profile_enabled": metrics is not None,
                "sql_profile_status": "collected" if metrics is not None else "not_collected",
                "explain_query_plan": explain,
                "levels": results,
                "errors": sum(int(item["errors"]) for item in results),
            }

        content = runtime.content or bundled_content()
        legacy_records = legacy_item_records(content)
        optimized_records = optimized_item_records(content)
        payload = {
            "comparison": {
                "before_full_item_catalogue": report(before_results, legacy_records),
                "after_manual_only_catalogue": report(after_results, optimized_records),
            },
            "errors": sum(
                int(item["errors"])
                for results in (before_results, after_results)
                for item in results
            ),
        }
    cleaned = not temporary_path.exists()
    for result in payload["comparison"].values():
        result["temporary_database_cleaned"] = cleaned
    return payload


async def _run_domain_front_index_comparison(
    users: int,
    batch_size: int,
    total_requests: int,
    levels: tuple[int, ...],
    *,
    profile_sql: bool | None = None,
    commands: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Compare domain-front indexes on one seeded runtime and database."""

    indexes = (
        (
            "idx_domain_front_participants_player",
            "CREATE INDEX IF NOT EXISTS idx_domain_front_participants_player "
            "ON domain_front_participants(player_id)",
        ),
        (
            "idx_domain_front_contributions_player",
            "CREATE INDEX IF NOT EXISTS idx_domain_front_contributions_player "
            "ON domain_front_contributions(player_id)",
        ),
        (
            "idx_domain_front_claims_player",
            "CREATE INDEX IF NOT EXISTS idx_domain_front_claims_player "
            "ON domain_front_claims(player_id)",
        ),
    )
    temporary_path: Path
    with tempfile.TemporaryDirectory(prefix="xiuxian-perf-") as data_dir:
        temporary_path = Path(data_dir)
        runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11", "qq.official"))
        await runtime.initialize()
        seed = _seed_database(runtime, users, batch_size)
        metrics = _instrument_repository(runtime, enabled=profile_sql)
        with sqlite3.connect(runtime.settings.database_path) as connection:
            for name, _ in indexes:
                connection.execute(f"DROP INDEX IF EXISTS {name}")
        explain_before = _explain(runtime.settings.database_path, 1)
        before_results = [
            asdict(await _measure(runtime, users, concurrency, total_requests, metrics, commands))
            for concurrency in levels
        ]
        with sqlite3.connect(runtime.settings.database_path) as connection:
            for _, statement in indexes:
                connection.execute(statement)
        explain_after = _explain(runtime.settings.database_path, 1)
        after_results = [
            asdict(await _measure(runtime, users, concurrency, total_requests, metrics, commands))
            for concurrency in levels
        ]
        await runtime.close()
        db_bytes = _db_size(runtime.settings.database_path)

        def report(results: list[dict[str, Any]], explain: dict[str, list[str]]) -> dict[str, Any]:
            return {
                "users": users,
                "seed": seed,
                "database_bytes_after_benchmark": db_bytes,
                "sql_profile_enabled": metrics is not None,
                "sql_profile_status": "collected" if metrics is not None else "not_collected",
                "explain_query_plan": explain,
                "levels": results,
                "errors": sum(int(item["errors"]) for item in results),
            }

        payload = {
            "comparison": {
                "before_without_domain_front_player_indexes": report(before_results, explain_before),
                "after_with_domain_front_player_indexes": report(after_results, explain_after),
            },
            "errors": sum(
                int(item["errors"])
                for results in (before_results, after_results)
                for item in results
            ),
        }
    cleaned = not temporary_path.exists()
    for result in payload["comparison"].values():
        result["temporary_database_cleaned"] = cleaned
    return payload


async def _run_mainline_prerequisite_comparison(
    users: int,
    batch_size: int,
    total_requests: int,
    levels: tuple[int, ...],
    *,
    profile_sql: bool | None = None,
    commands: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Compare per-stage and shared mainline prerequisite preparation once seeded."""

    import importlib

    repository_module = importlib.import_module(
        "nonebot_plugin_xiuxian_3.xiuxian.adventures.repository"
    )
    optimized = repository_module.mainline_prerequisites_met_many

    def per_stage(definitions: Iterable[Any], **kwargs: Any) -> tuple[bool, ...]:
        return tuple(
            repository_module.mainline_prerequisites_met(definition, **kwargs)
            for definition in definitions
        )

    temporary_path: Path
    with tempfile.TemporaryDirectory(prefix="xiuxian-perf-") as data_dir:
        temporary_path = Path(data_dir)
        runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11", "qq.official"))
        await runtime.initialize()
        seed = _seed_database(runtime, users, batch_size)
        explain = _explain(runtime.settings.database_path, 1)
        metrics = _instrument_repository(runtime, enabled=profile_sql)
        variants: dict[str, list[dict[str, Any]]] = {
            "before_per_stage_preparation": [],
            "after_shared_preparation": [],
        }
        try:
            for index, concurrency in enumerate(levels):
                for repetition in range(2):
                    before_first = (index + repetition) % 2 == 0
                    order = (
                        (
                            ("before_per_stage_preparation", per_stage),
                            ("after_shared_preparation", optimized),
                        )
                        if before_first
                        else (
                            ("after_shared_preparation", optimized),
                            ("before_per_stage_preparation", per_stage),
                        )
                    )
                    for label, evaluator in order:
                        repository_module.mainline_prerequisites_met_many = evaluator
                        result = asdict(
                            await _measure(
                                runtime,
                                users,
                                concurrency,
                                total_requests,
                                metrics,
                                commands,
                            )
                        )
                        result["repeat"] = repetition + 1
                        variants[label].append(result)
        finally:
            repository_module.mainline_prerequisites_met_many = optimized
            await runtime.close()
        db_bytes = _db_size(runtime.settings.database_path)

        def report(results: list[dict[str, Any]]) -> dict[str, Any]:
            return {
                "users": users,
                "seed": seed,
                "database_bytes_after_benchmark": db_bytes,
                "sql_profile_enabled": metrics is not None,
                "sql_profile_status": "collected" if metrics is not None else "not_collected",
                "explain_query_plan": explain,
                "levels": results,
                "errors": sum(int(item["errors"]) for item in results),
            }

        payload = {
            "comparison": {label: report(results) for label, results in variants.items()},
            "errors": sum(
                int(item["errors"])
                for results in variants.values()
                for item in results
            ),
        }
    cleaned = not temporary_path.exists()
    for result in payload["comparison"].values():
        result["temporary_database_cleaned"] = cleaned
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--users", type=int, default=int(os.getenv("XIUXIAN_PERF_USERS", "1000000")))
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, nargs="+", default=(1, 10, 50))
    parser.add_argument("--json-out", type=Path)
    compare = parser.add_mutually_exclusive_group()
    compare.add_argument(
        "--compare-domain-front-indexes",
        action="store_true",
        help="run before/after on the same deterministic domain-front dataset",
    )
    compare.add_argument(
        "--compare-mainline-prerequisites",
        action="store_true",
        help="compare shared vs per-stage mainline prerequisite preparation",
    )
    compare.add_argument(
        "--compare-connection-probe",
        action="store_true",
        help="compare the removed connection health probe without reseeding the fixture",
    )
    compare.add_argument(
        "--compare-manual-catalogue",
        action="store_true",
        help="compare manual-only catalogue iteration without reseeding the fixture",
    )
    parser.add_argument(
        "--profile-sql",
        action="store_true",
        help="collect traced SQL statements (otherwise sql_queries is null)",
    )
    parser.add_argument(
        "--command",
        choices=("我的状态", "挂机状态", "主线状态", "移动预览 玄天近郊"),
        help="measure one real command with all requests assigned to it",
    )
    args = parser.parse_args()
    if not 1 <= args.users <= 1_000_000:
        parser.error("--users must be between 1 and 1000000")
    if not 1 <= args.batch_size <= 10_000:
        parser.error("--batch-size must be between 1 and 10000")
    if not 1 <= args.requests <= 2_000:
        parser.error("--requests must be between 1 and 2000")
    levels = tuple(sorted(set(args.concurrency)))
    if any(level < 1 or level > 50 for level in levels):
        parser.error("--concurrency values must be between 1 and 50")
    commands = (args.command,) if args.command else None
    profile_sql = True if args.profile_sql else None
    if args.compare_connection_probe:
        payload = asyncio.run(
            _run_connection_probe_comparison(
                args.users,
                args.batch_size,
                args.requests,
                levels,
                profile_sql=profile_sql,
                commands=commands,
            )
        )
    elif args.compare_manual_catalogue:
        payload = asyncio.run(
            _run_manual_catalogue_comparison(
                args.users,
                args.batch_size,
                args.requests,
                levels,
                profile_sql=profile_sql,
                commands=commands,
            )
        )
    elif args.compare_domain_front_indexes:
        payload = asyncio.run(
            _run_domain_front_index_comparison(
                args.users,
                args.batch_size,
                args.requests,
                levels,
                profile_sql=profile_sql,
                commands=commands,
            )
        )
    elif args.compare_mainline_prerequisites:
        payload = asyncio.run(
            _run_mainline_prerequisite_comparison(
                args.users,
                args.batch_size,
                args.requests,
                levels,
                profile_sql=profile_sql,
                commands=commands,
            )
        )
    else:
        payload = asyncio.run(
            _run(
                args.users,
                args.batch_size,
                args.requests,
                levels,
                profile_sql=profile_sql,
                commands=commands,
            )
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if payload["errors"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
