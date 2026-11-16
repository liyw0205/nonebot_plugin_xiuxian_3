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
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
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
ARENA_SNAPSHOT_INSERT = """
INSERT INTO arena_snapshots(
    snapshot_id, player_id, status, arena_mode_key, rating, matchable_at,
    expires_at, snapshot_json, public_json, created_at, updated_at
) VALUES (?, ?, 'expired', 'arena.rank', 1000, ?, ?, ?, ?, ?, ?)
"""
ARENA_MATCH_INSERT = """
INSERT INTO arena_matches(
    match_id, challenger_id, defender_id, challenger_snapshot_id,
    defender_snapshot_id, arena_mode_key, status, outcome, rounds,
    score_counted, challenger_rating_delta, defender_rating_delta,
    snapshot_json, result_json, operation_id, created_at, settled_at
) VALUES (?, ?, ?, ?, ?, 'arena.rank', 'settled', ?, 3, 1, ?, ?, ?, ?, ?, ?, ?)
"""
ARENA_SEASON_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_arena_matches_settled_events "
    "ON arena_matches(settled_at, challenger_id, defender_id, outcome, "
    "score_counted, challenger_rating_delta, defender_rating_delta)"
)
EXPECTED_COMMAND_CODES = {
    "寄售物资 虚空晶体 1 100": "VOID_MARKET_ADMISSION",
}


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
    executor_queue_wait_ms: Percentiles
    executor_worker_count: int
    executor_max_active_workers: int
    connection_open_ms: Percentiles
    connection_count: int
    sql_queries: int | None
    companion_gear_queries: int | None
    expected_command_responses: dict[str, int]


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
        "player_stat_snapshot_ms": [],
        "player_equipment_snapshot_ms": [],
        "player_constitution_effect_ms": [],
        "player_manual_effects_ms": [],
        "player_stats_formula_ms": [],
        "player_stat_calculation_ms": [],
        "player_companion_carry_ms": [],
        "player_view_normalization_ms": [],
        "companion_status_view_ms": [],
        "companion_gear_batch_ms": [],
        "equipment_definition_provider_ms": [],
        "equipment_definition_build_ms": [],
        "item_resolution_ms": [],
        "idle_status_ms": [],
        "idle_preview_ms": [],
        "mainline_status_ms": [],
        "travel_preview_ms": [],
        "arena_season_board_ms": [],
        "sql_queries": [],
        "companion_gear_queries": [],
        "executor_queue_wait_ms": [],
        "executor_worker_count": [],
        "executor_active_workers": [],
    }
    repository = runtime.repository
    repository._inflight = _TimedSemaphore(runtime.settings.max_inflight, metrics["inflight_wait_ms"])

    def timed_method(target: Any, name: str, metric: str) -> None:
        original = getattr(target, name)
        setattr(target, name, _timed_callable(original, metrics[metric]))

    timed_method(repository, "_get_player_profile_sync", "player_profile_ms")
    timed_method(repository, "_build_player_stat_snapshot", "player_stat_snapshot_ms")
    timed_method(repository, "_battle_equipment_snapshot", "player_equipment_snapshot_ms")
    timed_method(repository, "companion_carry_snapshot", "player_companion_carry_ms")
    timed_method(repository, "_row_to_player", "player_view_normalization_ms")
    timed_method(repository, "_view_rows", "companion_status_view_ms")
    timed_method(repository, "_gear_snapshots_for_player", "companion_gear_batch_ms")
    timed_method(repository, "_get_idle_status_once", "idle_status_ms")
    timed_method(repository, "_preview_idle_once", "idle_preview_ms")
    timed_method(repository, "_get_mainline_status_sync", "mainline_status_ms")
    timed_method(repository, "_preview_travel_database_state", "travel_preview_ms")
    timed_method(repository, "_arena_season_board_once", "arena_season_board_ms")
    timed_method(runtime.application.void_material, "_resolve_item", "item_resolution_ms")
    original_connect = repository._connect

    def timed_connect() -> sqlite3.Connection:
        started = time.perf_counter()
        try:
            connection = original_connect()
            def trace(statement: str) -> None:
                normalized = statement.lstrip().upper()
                if normalized.startswith("PRAGMA"):
                    return
                metrics["sql_queries"].append(1.0)
                if "FROM COMPANION_GEAR_INSTANCES" in normalized:
                    metrics["companion_gear_queries"].append(1.0)

            connection.set_trace_callback(trace)
            return connection
        finally:
            metrics["connection_open_ms"].append((time.perf_counter() - started) * 1000)

    repository._connect = timed_connect
    return metrics


def _timed_callable(original: Any, samples: list[float]) -> Any:
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            samples.append((time.perf_counter() - started) * 1000)

    wrapped.__wrapped__ = original
    return wrapped


def _instrument_stat_helpers(metrics: dict[str, list[float]]) -> Any:
    import importlib

    targets = (
        (
            importlib.import_module("nonebot_plugin_xiuxian_3.xiuxian.stats.repository"),
            "constitution_effect_snapshot",
            "player_constitution_effect_ms",
        ),
        (
            importlib.import_module("nonebot_plugin_xiuxian_3.xiuxian.stats.repository"),
            "manual_effect_totals",
            "player_manual_effects_ms",
        ),
        (
            importlib.import_module("nonebot_plugin_xiuxian_3.xiuxian.stats.rules"),
            "stats_formula",
            "player_stats_formula_ms",
        ),
        (
            importlib.import_module("nonebot_plugin_xiuxian_3.xiuxian.stats.repository"),
            "stats_formula",
            "player_stats_formula_ms",
        ),
        (
            importlib.import_module("nonebot_plugin_xiuxian_3.xiuxian.stats.repository"),
            "build_stat_preview",
            "player_stat_calculation_ms",
        ),
    )
    originals: list[tuple[Any, str, Any]] = []
    for module, name, metric in targets:
        original = getattr(module, name)

        def timed(*args: Any, _original: Any = original, _metric: str = metric, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                return _original(*args, **kwargs)
            finally:
                metrics[_metric].append((time.perf_counter() - started) * 1000)

        originals.append((module, name, original))
        setattr(module, name, timed)

    def restore() -> None:
        for module, name, original in reversed(originals):
            setattr(module, name, original)

    return restore


def _instrument_executor(metrics: dict[str, list[float]]) -> Any:
    loop = asyncio.get_running_loop()
    original = loop.run_in_executor
    lock = threading.Lock()
    workers: set[int] = set()
    active = 0

    def measured_run_in_executor(executor: Any, function: Any, *args: Any) -> Any:
        submitted_at = time.perf_counter()

        def measured_function(*function_args: Any) -> Any:
            nonlocal active
            started_at = time.perf_counter()
            with lock:
                active += 1
                if not metrics["executor_worker_count"]:
                    workers.clear()
                workers.add(threading.get_ident())
                metrics["executor_queue_wait_ms"].append((started_at - submitted_at) * 1000)
                metrics["executor_worker_count"].append(float(len(workers)))
                metrics["executor_active_workers"].append(float(active))
            try:
                return function(*function_args)
            finally:
                with lock:
                    active -= 1

        return original(executor, measured_function, *args)

    loop.run_in_executor = measured_run_in_executor

    def restore() -> None:
        loop.run_in_executor = original

    return restore


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


def _index_size(path: Path, name: str) -> int | None:
    connection = sqlite3.connect(path)
    try:
        row = connection.execute(
            "SELECT COALESCE(SUM(pgsize), 0) FROM dbstat WHERE name = ?", (name,)
        ).fetchone()
        return int(row[0])
    except sqlite3.OperationalError:
        return None
    finally:
        connection.close()


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
    arena_matches = _seed_arena_history(runtime, path, users, now)
    return {
        "users": users,
        "domain_front_rows": users,
        "arena_matches": arena_matches,
        "seed_seconds": round(time.perf_counter() - started, 3),
        "db_bytes": _db_size(path),
    }


def _seed_companion_status_fixture(
    path: Path,
    users: int,
    *,
    companions_per_user: int = 5,
    gears_per_companion: int = 1,
) -> dict[str, int]:
    now = "2026-11-15T00:00:00+00:00"
    companions = []
    gears = []
    for number in range(users):
        player_id = number + 1
        for slot in range(companions_per_user):
            companion_id = number * companions_per_user + slot + 1
            instance_id = f"perf-companion-{companion_id:07d}"
            companions.append(
                (
                    instance_id,
                    player_id,
                    "beast.wood_rat",
                    "beast",
                    "active",
                    1,
                    0,
                    0,
                    100,
                    0,
                    "base",
                    0,
                    "{}",
                    now,
                    now,
                )
            )
            for gear_slot in range(gears_per_companion):
                gear_id = (companion_id - 1) * gears_per_companion + gear_slot + 1
                gears.append(
                    (
                        f"perf-companion-gear-{gear_id:07d}",
                        player_id,
                        companion_id,
                        "beast.gear.sack_small",
                        10000,
                        f"perf-companion-gear-op-{gear_id:07d}",
                        now,
                        now,
                    )
                )
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executemany(
            "INSERT INTO companion_instances(instance_id, player_id, companion_key, kind, status, "
            "level, experience, affinity, stamina, deployed, evolution_stage, skill_slots, "
            "snapshot_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            companions,
        )
        connection.executemany(
            "INSERT INTO companion_gear_instances(gear_instance_id, player_id, companion_instance_id, "
            "gear_key, status, durability_bp, operation_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'equipped', ?, ?, ?, ?)",
            gears,
        )
    return {
        "companions": len(companions),
        "gears": len(gears),
        "companions_per_user": companions_per_user,
        "gears_per_companion": gears_per_companion,
    }


def _seed_idle_preview_history(path: Path, users: int) -> int:
    timestamp = datetime.now(timezone.utc)
    now = timestamp.isoformat()
    business_date = timestamp.date().isoformat()
    rows = []
    for number in range(users):
        player_id = number + 1
        for label, route_key, status in (
            ("town", "idle.town_errand", "claimed"),
            ("herb", "idle.herb_vale_gather", "expired"),
        ):
            suffix = f"{label}-{number:07d}"
            rows.append(
                (
                    f"perf-idle-history-{suffix}",
                    player_id,
                    f"perf-idle-history-op-{suffix}",
                    route_key,
                    status,
                    business_date,
                    now,
                    now,
                    now,
                    now,
                    "{}",
                    "{}",
                    "{}",
                    now,
                    now,
                )
            )
    with sqlite3.connect(path) as connection:
        connection.executemany(
            "INSERT INTO idle_assignments(assignment_id, player_id, operation_id, route_key, "
            "status, business_date, starts_at, claim_at, max_claim_at, cancel_until, cost_json, "
            "snapshot_json, result_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def _prepare_idle_preview_fixture(path: Path) -> int:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE idle_assignments SET status = 'cancelled' "
            "WHERE status IN ('assigned', 'running')"
        )
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM idle_assignments "
                "WHERE status IN ('assigned', 'running')"
            ).fetchone()[0]
        )


def _seed_arena_history(runtime: Any, path: Path, users: int, now: str) -> int:
    if users < 2:
        return 0
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN")
        profiles: dict[int, dict[str, Any]] = {}
        for player_id in (1, 2):
            player = connection.execute(
                "SELECT * FROM players WHERE id = ?", (player_id,)
            ).fetchone()
            if player is None:
                raise RuntimeError("arena benchmark player seed is missing")
            profiles[player_id] = runtime.repository._arena_player_snapshot(
                connection, player, f"perf-arena-snapshot-{player_id:07d}"
            )

        snapshots = []
        matches = []
        for number in range(users):
            challenger_id = number + 1
            defender_id = (number + 1) % users + 1
            challenger_snapshot_id = f"perf-arena-snapshot-{challenger_id:07d}"
            defender_snapshot_id = f"perf-arena-snapshot-{defender_id:07d}"
            challenger_profile = dict(profiles[(challenger_id - 1) % 2 + 1])
            defender_profile = dict(profiles[(defender_id - 1) % 2 + 1])
            challenger_profile["snapshot_id"] = challenger_snapshot_id
            defender_profile["snapshot_id"] = defender_snapshot_id
            snapshots.append(
                (
                    challenger_snapshot_id,
                    challenger_id,
                    now,
                    now,
                    json.dumps(challenger_profile, ensure_ascii=False, sort_keys=True),
                    json.dumps(
                        {"snapshot_id": challenger_snapshot_id, "rating": 1000},
                        sort_keys=True,
                    ),
                    now,
                    now,
                )
            )
            outcome = "challenger_won" if number % 2 == 0 else "defender_won"
            challenger_delta = 5 if outcome == "challenger_won" else -5
            defender_delta = -challenger_delta
            operation_id = f"perf-arena-op-{number:07d}"
            snapshot = {
                "challenger": challenger_profile,
                "defender": defender_profile,
                "arena_mode_key": "arena.rank",
                "tactical_environment": {},
            }
            result = {
                "outcome": outcome,
                "rounds": 3,
                "score_counted": True,
                "challenger_rating_delta": challenger_delta,
                "defender_rating_delta": defender_delta,
                "mode_key": "arena.rank",
                "request_id": f"perf-arena-request-{number:07d}",
                "operation_id": operation_id,
                "tactical_environment": {},
            }
            matches.append(
                (
                    f"perf-arena-match-{number:07d}",
                    challenger_id,
                    defender_id,
                    challenger_snapshot_id,
                    defender_snapshot_id,
                    outcome,
                    challenger_delta,
                    defender_delta,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    json.dumps(result, ensure_ascii=False, sort_keys=True),
                    operation_id,
                    now,
                    now,
                )
            )
        connection.executemany(ARENA_SNAPSHOT_INSERT, snapshots)
        connection.executemany(ARENA_MATCH_INSERT, matches)
        connection.commit()
    return len(matches)


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


async def _request(
    runtime: Any,
    adapter: str,
    user_id: str,
    request_number: int,
    text: str,
) -> tuple[float, float, bool, bool]:
    started = time.perf_counter()
    try:
        normalized = _normalize(adapter, user_id, request_number, text)
        result = await runtime.adapters.dispatch(adapter, normalized.context, normalized.text)
        serialization_ms = _serialize_response(adapter, result)
        expected_code = EXPECTED_COMMAND_CODES.get(text)
        expected_response = expected_code is not None and result.code == expected_code
        failed = (
            result.code != expected_code
            if expected_code is not None
            else not result.ok
        )
        return (time.perf_counter() - started) * 1000, serialization_ms, failed, expected_response
    except Exception:
        return (time.perf_counter() - started) * 1000, 0.0, True, False


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
    commands = commands or (
        "我的状态",
        "挂机状态",
        "主线状态",
        "移动预览 玄天近郊",
        "竞技场赛季",
    )
    samples = tuple(
        (adapters[number % 2], f"perf-{number % users:07d}", commands[number % len(commands)])
        for number in range(total_requests)
    )
    latency: list[float] = []
    serialization: list[float] = []
    latency_by_command: dict[str, list[float]] = {command: [] for command in commands}
    errors_by_command: dict[str, int] = {command: 0 for command in commands}
    expected_responses_by_command: dict[str, int] = {command: 0 for command in commands}
    errors = 0
    if metrics is not None:
        for values in metrics.values():
            values.clear()
    before_cpu = resource.getrusage(resource.RUSAGE_SELF)
    cursor = 0
    while cursor < len(samples):
        batch = samples[cursor : cursor + concurrency]
        values = await asyncio.gather(
            *(
                _request(
                    runtime,
                    adapter,
                    user_id,
                    cursor + offset,
                    command,
                )
                for offset, (adapter, user_id, command) in enumerate(batch)
            )
        )
        for offset, (request_latency, response_serialization, failed, expected_response) in enumerate(values):
            latency.append(request_latency)
            serialization.append(response_serialization)
            errors += int(failed)
            command = batch[offset][2]
            latency_by_command[command].append(request_latency)
            errors_by_command[command] += int(failed)
            expected_responses_by_command[command] += int(expected_response)
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
            if key not in {
                "inflight_wait_ms",
                "connection_open_ms",
                "sql_queries",
                "companion_gear_queries",
                "executor_queue_wait_ms",
                "executor_worker_count",
                "executor_active_workers",
            }
        },
        inflight_wait_ms=_percentiles((metrics or {}).get("inflight_wait_ms", ())),
        executor_queue_wait_ms=_percentiles((metrics or {}).get("executor_queue_wait_ms", ())),
        executor_worker_count=int(max((metrics or {}).get("executor_worker_count", ()), default=0)),
        executor_max_active_workers=int(max((metrics or {}).get("executor_active_workers", ()), default=0)),
        connection_open_ms=_percentiles((metrics or {}).get("connection_open_ms", ())),
        connection_count=len(runtime.repository._connection_registry),
        sql_queries=(len(metrics["sql_queries"]) if metrics is not None else None),
        companion_gear_queries=(
            len(metrics["companion_gear_queries"]) if metrics is not None else None
        ),
        expected_command_responses=expected_responses_by_command,
    )


def _explain(path: Path, player_id: int) -> dict[str, list[str]]:
    queries = {
        "player_lookup": "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
        "stats_equipment": (
            "SELECT * FROM equipment_instances WHERE player_id = ? AND status = 'active' "
            "AND equipped = 1 AND durability_bp > 0 ORDER BY id"
        ),
        "stats_constitution": "SELECT snapshot_json FROM constitution_profiles WHERE player_id = ? LIMIT 1",
        "stats_companion_carry": (
            "SELECT g.gear_instance_id, g.gear_key, g.durability_bp "
            "FROM companion_gear_instances g JOIN companion_instances c ON c.id=g.companion_instance_id "
            "WHERE g.player_id=? AND g.status='equipped' AND g.durability_bp>0 "
            "AND c.kind='beast' AND c.deployed=1 AND c.status IN ('active', 'available') ORDER BY g.id"
        ),
        "idle_status": "SELECT * FROM idle_assignments WHERE player_id = ? AND status = 'running' ORDER BY id DESC LIMIT 1",
        "idle_active_preview": "SELECT 1 FROM idle_assignments WHERE player_id = ? AND status IN ('assigned', 'running') LIMIT 1",
        "idle_daily_route": "SELECT COUNT(*) AS count FROM idle_assignments WHERE player_id = ? AND route_key = ? AND business_date = ? AND status IN ('claimed', 'expired')",
        "idle_daily_grouped": "SELECT route_key, COUNT(*) AS count FROM idle_assignments WHERE player_id = ? AND business_date = ? AND status IN ('claimed', 'expired') AND route_key IN (?, ?) GROUP BY route_key",
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
        "arena_season_events": "SELECT challenger_id, defender_id, outcome, score_counted, settled_at, challenger_rating_delta, defender_rating_delta FROM arena_matches WHERE settled_at < ?",
    }
    params = {
        "player_lookup": ("onebot.v11", f"perf-{player_id - 1:07d}"),
        "stats_equipment": (player_id,),
        "stats_constitution": (player_id,),
        "stats_companion_carry": (player_id,),
        "idle_status": (player_id,),
        "idle_active_preview": (player_id,),
        "idle_daily_route": (player_id, "idle.herb_vale_gather", "2026-11-15"),
        "idle_daily_grouped": (player_id, "2026-11-15", "idle.herb_vale_gather", "idle.town_errand"),
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
        "arena_season_events": ("2026-11-16T00:00:00+00:00",),
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
        restore_executor = _instrument_executor(metrics) if metrics is not None else None
        restore_stat_helpers = _instrument_stat_helpers(metrics) if metrics is not None else None
        try:
            results = [
                asdict(await _measure(runtime, users, concurrency, total_requests, metrics, commands))
                for concurrency in levels
            ]
        finally:
            if restore_executor is not None:
                restore_executor()
            if restore_stat_helpers is not None:
                restore_stat_helpers()
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


async def _run_arena_season_event_comparison(
    users: int,
    batch_size: int,
    total_requests: int,
    levels: tuple[int, ...],
    *,
    profile_sql: bool | None = None,
    commands: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Compare per-window and shared match-history reads on one fixture."""

    selected_commands = commands or ("竞技场赛季",)
    if selected_commands != ("竞技场赛季",):
        raise ValueError("arena season comparison only supports the season-board command")

    temporary_path: Path
    with tempfile.TemporaryDirectory(prefix="xiuxian-perf-") as data_dir:
        temporary_path = Path(data_dir)
        runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11", "qq.official"))
        await runtime.initialize()
        seed = _seed_database(runtime, users, batch_size)
        explain = _explain(runtime.settings.database_path, 1)
        metrics = _instrument_repository(runtime, enabled=profile_sql)
        repository = runtime.repository
        shared_reader = repository._arena_season_events_for_board_windows

        def separate_readers(connection: sqlite3.Connection, ends: tuple[Any, ...]):
            return {
                end: repository._season_events(connection, end)
                for end in dict.fromkeys(ends)
            }

        variants: dict[str, list[dict[str, Any]]] = {
            "before_separate_window_history_reads": [],
            "after_shared_history_read": [],
        }
        try:
            for index, concurrency in enumerate(levels):
                for repetition in range(2):
                    before_first = (index + repetition) % 2 == 0
                    order = (
                        (
                            ("before_separate_window_history_reads", separate_readers),
                            ("after_shared_history_read", shared_reader),
                        )
                        if before_first
                        else (
                            ("after_shared_history_read", shared_reader),
                            ("before_separate_window_history_reads", separate_readers),
                        )
                    )
                    for label, reader in order:
                        repository._arena_season_cache_enabled = label == "after_shared_history_read"
                        cache = getattr(repository, "_arena_season_cache", None)
                        if cache is not None:
                            cache.clear()
                        repository._arena_season_events_for_board_windows = reader
                        result = asdict(
                            await _measure(
                                runtime,
                                users,
                                concurrency,
                                total_requests,
                                metrics,
                                selected_commands,
                            )
                        )
                        result["repeat"] = repetition + 1
                        variants[label].append(result)
        finally:
            repository._arena_season_events_for_board_windows = shared_reader
            repository._arena_season_cache_enabled = True
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


async def _run_arena_season_cache_comparison(
    users: int,
    batch_size: int,
    total_requests: int,
    levels: tuple[int, ...],
    *,
    profile_sql: bool | None = None,
    commands: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Compare repeated season-history work with the per-connection cache."""

    selected_commands = commands or ("竞技场赛季",)
    if selected_commands != ("竞技场赛季",):
        raise ValueError("arena season cache comparison only supports the season-board command")

    temporary_path: Path
    with tempfile.TemporaryDirectory(prefix="xiuxian-perf-") as data_dir:
        temporary_path = Path(data_dir)
        runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11", "qq.official"))
        await runtime.initialize()
        seed = _seed_database(runtime, users, batch_size)
        explain = _explain(runtime.settings.database_path, 1)
        metrics = _instrument_repository(runtime, enabled=profile_sql)
        repository = runtime.repository
        original_board = repository._arena_season_board_once
        current_label = ""
        outputs: dict[str, list[str]] = {
            "before_without_cache": [],
            "after_event_and_board_cache": [],
        }

        def recording_board(*args: Any, **kwargs: Any) -> dict[str, Any]:
            payload = original_board(*args, **kwargs)
            if current_label and len(outputs[current_label]) < 1:
                outputs[current_label].append(
                    json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                )
            return payload

        repository._arena_season_board_once = recording_board
        variants: dict[str, list[dict[str, Any]]] = {
            "before_without_cache": [],
            "after_event_and_board_cache": [],
        }
        try:
            for index, concurrency in enumerate(levels):
                for repetition in range(2):
                    before_first = (index + repetition) % 2 == 0
                    order = (
                        ("before_without_cache", False),
                        ("after_event_and_board_cache", True),
                    ) if before_first else (
                        ("after_event_and_board_cache", True),
                        ("before_without_cache", False),
                    )
                    for label, enabled in order:
                        current_label = label
                        repository._arena_season_cache_enabled = enabled
                        cache = getattr(repository, "_arena_season_cache", None)
                        if cache is not None:
                            cache.clear()
                        result = asdict(
                            await _measure(
                                runtime,
                                users,
                                concurrency,
                                total_requests,
                                metrics,
                                selected_commands,
                            )
                        )
                        result["repeat"] = repetition + 1
                        variants[label].append(result)
        finally:
            current_label = ""
            repository._arena_season_board_once = original_board
            repository._arena_season_cache_enabled = True
            await runtime.close()
        db_bytes = _db_size(runtime.settings.database_path)
        output_equivalent = outputs["before_without_cache"] == outputs["after_event_and_board_cache"]

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
            "board_outputs_equivalent": output_equivalent,
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


async def _run_idle_preview_comparison(
    users: int,
    batch_size: int,
    total_requests: int,
    levels: tuple[int, ...],
    *,
    profile_sql: bool | None = None,
    commands: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Compare repeated per-route state reads with one shared preview context."""

    selected_commands = commands or ("挂机预览",)
    if selected_commands != ("挂机预览",):
        raise ValueError("idle preview comparison only supports the all-route preview command")

    import importlib
    from types import SimpleNamespace

    idle_rules = importlib.import_module(
        "nonebot_plugin_xiuxian_3.xiuxian.specials.idle_rules"
    )
    player_module = importlib.import_module("nonebot_plugin_xiuxian_3.xiuxian.utils.player")
    temporary_path: Path
    with tempfile.TemporaryDirectory(prefix="xiuxian-perf-") as data_dir:
        temporary_path = Path(data_dir)
        runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11", "qq.official"))
        await runtime.initialize()
        seed = _seed_database(runtime, users, batch_size)
        seed["idle_preview_history_rows"] = _seed_idle_preview_history(
            runtime.settings.database_path, users
        )
        seed["active_idle_rows_for_preview"] = _prepare_idle_preview_fixture(
            runtime.settings.database_path
        )
        seed["db_bytes"] = _db_size(runtime.settings.database_path)
        explain = _explain(runtime.settings.database_path, 1)
        metrics = _instrument_repository(runtime, enabled=profile_sql)
        restore_executor = _instrument_executor(metrics) if metrics is not None else None
        repository = runtime.repository
        optimized_preview = repository._preview_idle_once

        def repeated_state_preview(
            platform: str, platform_user_id: str, route_key: str | None
        ) -> tuple[Any, ...]:
            requested = (
                (idle_rules.resolve_route(route_key, repository.content),)
                if route_key
                else idle_rules.idle_route_order(repository.content)
            )
            now = repository._now()
            with repository._connect() as connection:
                player = repository._require_player(
                    connection, platform, platform_user_id, writable=False
                )
                previews = []
                for definition in requested:
                    active_idle = connection.execute(
                        "SELECT 1 FROM idle_assignments WHERE player_id = ? "
                        "AND status IN ('assigned', 'running') LIMIT 1",
                        (player["id"],),
                    ).fetchone() is not None
                    active_long_action = repository._has_active_long_action(
                        connection, int(player["id"])
                    )
                    daily_row = connection.execute(
                        "SELECT COUNT(*) AS count FROM idle_assignments "
                        "WHERE player_id = ? AND route_key = ? AND business_date = ? "
                        "AND status IN ('claimed', 'expired')",
                        (player["id"], definition.key, now.date().isoformat()),
                    ).fetchone()
                    shared_state = SimpleNamespace(
                        local_reputation=player_module.player_reputation_state(
                            connection, int(player["id"])
                        ).local,
                        active_idle=active_idle,
                        active_long_action=active_long_action,
                        daily_used={
                            definition.key: int(daily_row["count"])
                            if daily_row is not None
                            else 0
                        },
                    )
                    previews.append(
                        repository._idle_preview(
                            connection, player, definition, now, shared_state
                        )
                    )
                return tuple(previews)

        def legacy_timed_preview(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                return repeated_state_preview(*args, **kwargs)
            finally:
                if metrics is not None:
                    metrics["idle_preview_ms"].append(
                        (time.perf_counter() - started) * 1000
                    )

        variants: dict[str, list[dict[str, Any]]] = {
            "before_repeated_route_state_reads": [],
            "after_shared_preview_state": [],
        }
        try:
            baseline_records = repeated_state_preview("onebot.v11", "perf-0000000", None)
            optimized_records = optimized_preview("onebot.v11", "perf-0000000", None)
            correctness_equivalent = [asdict(record) for record in baseline_records] == [
                asdict(record) for record in optimized_records
            ]
            if not correctness_equivalent:
                raise AssertionError("idle preview results differ between comparison variants")
            for level_index, concurrency in enumerate(levels):
                for repetition in range(2):
                    before_first = (level_index + repetition) % 2 == 0
                    order = (
                        (
                            ("before_repeated_route_state_reads", legacy_timed_preview),
                            ("after_shared_preview_state", optimized_preview),
                        )
                        if before_first
                        else (
                            ("after_shared_preview_state", optimized_preview),
                            ("before_repeated_route_state_reads", legacy_timed_preview),
                        )
                    )
                    for label, preview in order:
                        repository._preview_idle_once = preview
                        result = asdict(
                            await _measure(
                                runtime,
                                users,
                                concurrency,
                                total_requests,
                                metrics,
                                selected_commands,
                            )
                        )
                        result["repeat"] = repetition + 1
                        variants[label].append(result)
        finally:
            if restore_executor is not None:
                restore_executor()
            repository._preview_idle_once = optimized_preview
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
            "preview_records_equivalent": correctness_equivalent,
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


async def _run_arena_season_index_comparison(
    users: int,
    batch_size: int,
    total_requests: int,
    levels: tuple[int, ...],
    *,
    profile_sql: bool | None = None,
    commands: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Compare the covering history index on one seeded arena fixture."""

    selected_commands = commands or ("竞技场赛季",)
    if selected_commands != ("竞技场赛季",):
        raise ValueError("arena season index comparison only supports the season-board command")

    temporary_path: Path
    with tempfile.TemporaryDirectory(prefix="xiuxian-perf-") as data_dir:
        temporary_path = Path(data_dir)
        runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11", "qq.official"))
        await runtime.initialize()
        seed = _seed_database(runtime, users, batch_size)
        database_path = runtime.settings.database_path
        metrics = _instrument_repository(runtime, enabled=profile_sql)
        with sqlite3.connect(database_path) as connection:
            connection.execute("DROP INDEX IF EXISTS idx_arena_matches_settled_events")
        explain_before = _explain(database_path, 1)
        variants: dict[str, list[dict[str, Any]]] = {
            "before_without_covering_index": [],
            "after_with_covering_index": [],
        }
        index_build_ms: list[float] = []
        restore_executor = _instrument_executor(metrics) if metrics is not None else None
        try:
            for index, concurrency in enumerate(levels):
                for repetition in range(2):
                    before_first = (index + repetition) % 2 == 0
                    order = (
                        ("before_without_covering_index", "after_with_covering_index")
                        if before_first
                        else ("after_with_covering_index", "before_without_covering_index")
                    )
                    for label in order:
                        connection = sqlite3.connect(database_path)
                        try:
                            if label == "after_with_covering_index":
                                started = time.perf_counter()
                                connection.execute(ARENA_SEASON_INDEX_SQL)
                                connection.commit()
                                index_build_ms.append((time.perf_counter() - started) * 1000)
                            else:
                                connection.execute(
                                    "DROP INDEX IF EXISTS idx_arena_matches_settled_events"
                                )
                                connection.commit()
                        finally:
                            connection.close()
                        result = asdict(
                            await _measure(
                                runtime,
                                users,
                                concurrency,
                                total_requests,
                                metrics,
                                selected_commands,
                            )
                        )
                        result["repeat"] = repetition + 1
                        variants[label].append(result)
        finally:
            if restore_executor is not None:
                restore_executor()
            await runtime.close()
        connection = sqlite3.connect(database_path)
        try:
            started = time.perf_counter()
            connection.execute(ARENA_SEASON_INDEX_SQL)
            connection.commit()
            index_build_ms.append((time.perf_counter() - started) * 1000)
        finally:
            connection.close()
        explain_after = _explain(database_path, 1)
        db_bytes = _db_size(database_path)
        index_bytes = _index_size(database_path, "idx_arena_matches_settled_events")

        def report(
            results: list[dict[str, Any]], explain: dict[str, list[str]], *, indexed: bool
        ) -> dict[str, Any]:
            return {
                "users": users,
                "seed": seed,
                "database_bytes_after_benchmark": db_bytes,
                "index_bytes": index_bytes if indexed else 0,
                "index_build_ms": index_build_ms if indexed else [],
                "sql_profile_enabled": metrics is not None,
                "sql_profile_status": "collected" if metrics is not None else "not_collected",
                "explain_query_plan": explain,
                "levels": results,
                "errors": sum(int(item["errors"]) for item in results),
            }

        payload = {
            "comparison": {
                "before_without_covering_index": report(
                    variants["before_without_covering_index"], explain_before, indexed=False
                ),
                "after_with_covering_index": report(
                    variants["after_with_covering_index"], explain_after, indexed=True
                ),
            },
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


async def _run_arena_season_top_n_comparison(
    users: int,
    batch_size: int,
    total_requests: int,
    levels: tuple[int, ...],
    *,
    profile_sql: bool | None = None,
    commands: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Compare complete ranking sorts with top-N selection on one arena fixture."""

    selected_commands = commands or ("竞技场赛季",)
    if selected_commands != ("竞技场赛季",):
        raise ValueError("arena top-N comparison only supports the season-board command")

    from nonebot_plugin_xiuxian_3.xiuxian.specials import arena_season as arena_rules
    from nonebot_plugin_xiuxian_3.xiuxian.specials import (
        arena_season_repository as arena_repository_module,
    )

    temporary_path: Path
    with tempfile.TemporaryDirectory(prefix="xiuxian-perf-") as data_dir:
        temporary_path = Path(data_dir)
        runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11", "qq.official"))
        await runtime.initialize()
        seed = _seed_database(runtime, users, batch_size)
        database_path = runtime.settings.database_path
        explain = _explain(database_path, 1)
        metrics = _instrument_repository(runtime, enabled=profile_sql)
        restore_executor = _instrument_executor(metrics) if metrics is not None else None
        optimized_builder = arena_repository_module.build_board

        def full_sort_then_slice(
            events: Iterable[Any],
            *,
            start: Any,
            end: Any,
            base_rating: int = arena_rules.BASE_RATING,
            limit: int | None = None,
        ) -> Any:
            return arena_rules.build_board(
                events,
                start=start,
                end=end,
                base_rating=base_rating,
            )

        repository = runtime.repository
        try:
            arena_repository_module.build_board = full_sort_then_slice
            before_payload = repository._arena_season_board_once(
                "onebot.v11", "perf-0000000", None
            )
            arena_repository_module.build_board = optimized_builder
            after_payload = repository._arena_season_board_once(
                "onebot.v11", "perf-0000000", None
            )
            board_results_equivalent = before_payload == after_payload
            if not board_results_equivalent:
                raise AssertionError("arena season board differs between full-sort and top-N variants")

            variants: dict[str, list[dict[str, Any]]] = {
                "before_full_sort_then_slice": [],
                "after_top_n_selection": [],
            }
            for level_index, concurrency in enumerate(levels):
                for repetition in range(2):
                    before_first = (level_index + repetition) % 2 == 0
                    order = (
                        (
                            ("before_full_sort_then_slice", full_sort_then_slice),
                            ("after_top_n_selection", optimized_builder),
                        )
                        if before_first
                        else (
                            ("after_top_n_selection", optimized_builder),
                            ("before_full_sort_then_slice", full_sort_then_slice),
                        )
                    )
                    for label, builder in order:
                        arena_repository_module.build_board = builder
                        result = asdict(
                            await _measure(
                                runtime,
                                users,
                                concurrency,
                                total_requests,
                                metrics,
                                selected_commands,
                            )
                        )
                        result["repeat"] = repetition + 1
                        variants[label].append(result)
        finally:
            arena_repository_module.build_board = optimized_builder
            if restore_executor is not None:
                restore_executor()
            await runtime.close()

        db_bytes = _db_size(database_path)

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
            "board_results_equivalent": board_results_equivalent,
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


async def _run_player_stats_formula_cache_comparison(
    users: int,
    batch_size: int,
    total_requests: int,
    levels: tuple[int, ...],
    *,
    profile_sql: bool | None = None,
    commands: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Compare uncached and repository-scoped formula reuse on one player fixture."""

    selected_commands = commands or ("我的状态",)
    if selected_commands != ("我的状态",):
        raise ValueError("player stats formula comparison only supports 我的状态")

    from nonebot_plugin_xiuxian_3.xiuxian.stats import repository as stats_repository_module

    temporary_path: Path
    with tempfile.TemporaryDirectory(prefix="xiuxian-perf-") as data_dir:
        temporary_path = Path(data_dir)
        runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11", "qq.official"))
        await runtime.initialize()
        seed = _seed_database(runtime, users, batch_size)
        database_path = runtime.settings.database_path
        explain = _explain(database_path, 1)
        metrics = _instrument_repository(runtime, enabled=profile_sql)
        restore_executor = _instrument_executor(metrics) if metrics is not None else None
        restore_stat_helpers = _instrument_stat_helpers(metrics) if metrics is not None else None
        repository = runtime.repository
        cached_provider = repository._stats_formula_for_snapshot

        def uncached_provider(content: Any) -> Any:
            return stats_repository_module.stats_formula(content)

        try:
            repository._stats_formula_for_snapshot = uncached_provider
            uncached_profile = repository._get_player_profile_sync("onebot.v11", "perf-0000000")
            repository._stats_formula_for_snapshot = cached_provider
            cached_profile = repository._get_player_profile_sync("onebot.v11", "perf-0000000")
            profile_results_equivalent = uncached_profile == cached_profile
            if not profile_results_equivalent:
                raise AssertionError("player profile differs between uncached and cached formula variants")

            variants: dict[str, list[dict[str, Any]]] = {
                "before_uncached_formula": [],
                "after_repository_formula_cache": [],
            }
            for level_index, concurrency in enumerate(levels):
                for repetition in range(4):
                    before_first = (level_index + repetition) % 2 == 0
                    order = (
                        (
                            ("before_uncached_formula", uncached_provider),
                            ("after_repository_formula_cache", cached_provider),
                        )
                        if before_first
                        else (
                            ("after_repository_formula_cache", cached_provider),
                            ("before_uncached_formula", uncached_provider),
                        )
                    )
                    for label, provider in order:
                        repository._stats_formula_for_snapshot = provider
                        result = asdict(
                            await _measure(
                                runtime,
                                users,
                                concurrency,
                                total_requests,
                                metrics,
                                selected_commands,
                            )
                        )
                        result["repeat"] = repetition + 1
                        variants[label].append(result)
        finally:
            repository._stats_formula_for_snapshot = cached_provider
            if restore_executor is not None:
                restore_executor()
            if restore_stat_helpers is not None:
                restore_stat_helpers()
            await runtime.close()

        db_bytes = _db_size(database_path)

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
            "profile_results_equivalent": profile_results_equivalent,
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


async def _run_player_profile_projection_comparison(
    users: int,
    batch_size: int,
    total_requests: int,
    levels: tuple[int, ...],
    *,
    profile_sql: bool | None = None,
    commands: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Compare the previous duplicate profile normalization with reuse."""

    selected_commands = commands or ("我的状态",)
    if selected_commands != ("我的状态",):
        raise ValueError("player profile projection comparison only supports 我的状态")

    from nonebot_plugin_xiuxian_3.xiuxian.player import repository as player_repository_module

    temporary_path: Path
    with tempfile.TemporaryDirectory(prefix="xiuxian-perf-") as data_dir:
        temporary_path = Path(data_dir)
        runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11", "qq.official"))
        await runtime.initialize()
        seed = _seed_database(runtime, users, batch_size)
        database_path = runtime.settings.database_path
        explain = _explain(database_path, 1)
        metrics = _instrument_repository(runtime, enabled=profile_sql)
        restore_executor = _instrument_executor(metrics) if metrics is not None else None
        restore_stat_helpers = _instrument_stat_helpers(metrics) if metrics is not None else None
        original_player_values = player_repository_module.player_values
        calls = 0

        def profile_values(row: Any, *, duplicate: bool) -> Any:
            nonlocal calls
            calls += 1
            values = original_player_values(row)
            if duplicate:
                calls += 1
                values = original_player_values(row)
            return values

        def set_variant(duplicate: bool) -> None:
            player_repository_module.player_values = lambda row: profile_values(
                row, duplicate=duplicate
            )

        def response_contract(result: Any) -> tuple[Any, ...]:
            return (
                result.ok,
                result.code,
                result.message,
                result.operation_id,
                result.data,
                result.retryable,
                result.actions,
            )

        async def profile_pair(duplicate: bool) -> list[Any]:
            set_variant(duplicate)
            results = []
            for request_number, adapter in enumerate(("onebot.v11", "qq.official")):
                normalized = _normalize(adapter, "perf-0000000", request_number, "我的状态")
                results.append(
                    await runtime.adapters.dispatch(adapter, normalized.context, normalized.text)
                )
            return results

        try:
            before_equivalence = await profile_pair(True)
            after_equivalence = await profile_pair(False)
            profile_results_equivalent = tuple(map(response_contract, before_equivalence)) == tuple(
                map(response_contract, after_equivalence)
            )
            if not profile_results_equivalent:
                raise AssertionError("player profile differs between duplicate and reused projections")

            variants: dict[str, list[dict[str, Any]]] = {
                "before_repeated_profile_projection": [],
                "after_shared_profile_projection": [],
            }
            for level_index, concurrency in enumerate(levels):
                for repetition in range(4):
                    before_first = (level_index + repetition) % 2 == 0
                    order = (
                        (
                            ("before_repeated_profile_projection", True),
                            ("after_shared_profile_projection", False),
                        )
                        if before_first
                        else (
                            ("after_shared_profile_projection", False),
                            ("before_repeated_profile_projection", True),
                        )
                    )
                    for label, duplicate in order:
                        set_variant(duplicate)
                        # Equalize executor/thread creation before comparing the
                        # steady-state command path; warmup samples are discarded.
                        await _measure(
                            runtime,
                            users,
                            concurrency,
                            max(1, min(8, total_requests // 4)),
                            metrics,
                            selected_commands,
                        )
                        calls = 0
                        result = asdict(
                            await _measure(
                                runtime,
                                users,
                                concurrency,
                                total_requests,
                                metrics,
                                selected_commands,
                            )
                        )
                        result["repeat"] = repetition + 1
                        result["player_value_normalization_calls"] = calls
                        variants[label].append(result)
        finally:
            player_repository_module.player_values = original_player_values
            if restore_executor is not None:
                restore_executor()
            if restore_stat_helpers is not None:
                restore_stat_helpers()
            await runtime.close()

        db_bytes = _db_size(database_path)

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
            "profile_results_equivalent": profile_results_equivalent,
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


async def _run_equipment_definition_cache_comparison(
    users: int,
    batch_size: int,
    total_requests: int,
    levels: tuple[int, ...],
    *,
    profile_sql: bool | None = None,
    commands: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Compare direct catalogue validation with per-application bundle reuse."""

    from nonebot_plugin_xiuxian_3.xiuxian.advancement import equipment_use_cases

    selected_commands = commands or ("法器预览", "重铸预览")
    if not selected_commands or any(command not in {"法器预览", "重铸预览"} for command in selected_commands):
        raise ValueError("equipment definition comparison only supports 法器预览 and 重铸预览")

    temporary_path: Path
    with tempfile.TemporaryDirectory(prefix="xiuxian-perf-") as data_dir:
        temporary_path = Path(data_dir)
        runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11", "qq.official"))
        await runtime.initialize()
        seed = _seed_database(runtime, users, batch_size)
        database_path = runtime.settings.database_path
        await asyncio.sleep(0.05)
        recovery_task = runtime._dispatch_recovery_task
        if recovery_task is not None:
            recovery_task.cancel()
            try:
                await recovery_task
            except asyncio.CancelledError:
                pass
            runtime._dispatch_recovery_task = None
        metrics = _instrument_repository(runtime, enabled=profile_sql)
        equipment_application = runtime.application.equipment
        cached_provider = equipment_application._equipment_definitions
        original_builder = equipment_use_cases.equipment_definitions
        content = equipment_application._content()
        item_record_count = len(content.list("item", include_locked=False))
        cache_definition_count = len(cached_provider(content))

        def uncached_provider(bundle: Any) -> Any:
            return equipment_use_cases.equipment_definitions(bundle)

        def timed_provider(provider: Any) -> Any:
            def measure_provider(bundle: Any) -> Any:
                started = time.perf_counter()
                try:
                    return provider(bundle)
                finally:
                    if metrics is not None:
                        metrics["equipment_definition_provider_ms"].append(
                            (time.perf_counter() - started) * 1000
                        )

            return measure_provider

        def timed_builder(bundle: Any) -> Any:
            started = time.perf_counter()
            try:
                return original_builder(bundle)
            finally:
                if metrics is not None:
                    metrics["equipment_definition_build_ms"].append(
                        (time.perf_counter() - started) * 1000
                    )

        async def preview_results(provider: Any) -> list[Any]:
            equipment_application._equipment_definitions = timed_provider(provider)
            results = []
            for request_number, adapter in enumerate(("onebot.v11", "qq.official")):
                for command in selected_commands:
                    normalized = _normalize(adapter, "perf-0000000", request_number, command)
                    results.append(
                        await runtime.adapters.dispatch(adapter, normalized.context, normalized.text)
                    )
            return results

        def response_contract(result: Any) -> tuple[Any, ...]:
            return (
                result.ok,
                result.code,
                result.message,
                result.operation_id,
                result.data,
                result.retryable,
                result.actions,
            )

        try:
            equipment_use_cases.equipment_definitions = timed_builder
            before_equivalence = await preview_results(uncached_provider)
            equipment_application._equipment_definition_cache = None
            after_equivalence = await preview_results(cached_provider)
            outputs_equivalent = tuple(map(response_contract, before_equivalence)) == tuple(
                map(response_contract, after_equivalence)
            )
            if not outputs_equivalent:
                raise AssertionError("equipment preview responses differ between uncached and cached variants")

            variants: dict[str, list[dict[str, Any]]] = {
                "before_full_definition_build": [],
                "after_bundle_identity_cache": [],
            }
            for level_index, concurrency in enumerate(levels):
                for repetition in range(2):
                    before_first = (level_index + repetition) % 2 == 0
                    order = (
                        (
                            ("before_full_definition_build", uncached_provider),
                            ("after_bundle_identity_cache", cached_provider),
                        )
                        if before_first
                        else (
                            ("after_bundle_identity_cache", cached_provider),
                            ("before_full_definition_build", uncached_provider),
                        )
                    )
                    for label, provider in order:
                        equipment_application._equipment_definitions = timed_provider(provider)
                        if label == "after_bundle_identity_cache":
                            equipment_application._equipment_definition_cache = None
                        result = asdict(
                            await _measure(
                                runtime,
                                users,
                                concurrency,
                                total_requests,
                                metrics,
                                selected_commands,
                            )
                        )
                        result["repeat"] = repetition + 1
                        result["equipment_definition_build_count"] = len(
                            metrics["equipment_definition_build_ms"]
                            if metrics is not None
                            else ()
                        )
                        variants[label].append(result)
        finally:
            equipment_use_cases.equipment_definitions = original_builder
            equipment_application._equipment_definitions = cached_provider
            await runtime.close()

        db_bytes = _db_size(database_path)

        def report(results: list[dict[str, Any]]) -> dict[str, Any]:
            return {
                "users": users,
                "seed": seed,
                "database_bytes_after_benchmark": db_bytes,
                "item_records": item_record_count,
                "equipment_definitions": cache_definition_count,
                "sql_profile_enabled": metrics is not None,
                "sql_profile_status": "collected" if metrics is not None else "not_collected",
                "explain_query_plan": {"preview_database_access": ["none"]},
                "levels": results,
                "errors": sum(int(item["errors"]) for item in results),
            }

        payload = {
            "comparison": {label: report(results) for label, results in variants.items()},
            "preview_outputs_equivalent": outputs_equivalent,
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


async def _run_void_material_item_cache_comparison(
    users: int,
    batch_size: int,
    total_requests: int,
    levels: tuple[int, ...],
    *,
    profile_sql: bool | None = None,
    commands: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Compare linear item alias scans with bundle-scoped alias reuse."""

    selected_commands = commands or ("寄售物资 虚空晶体 1 100",)
    if selected_commands != ("寄售物资 虚空晶体 1 100",):
        raise ValueError("void material item comparison only supports the admission-gated list command")

    temporary_path: Path
    with tempfile.TemporaryDirectory(prefix="xiuxian-perf-") as data_dir:
        temporary_path = Path(data_dir)
        runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11", "qq.official"))
        await runtime.initialize()
        seed = _seed_database(runtime, users, batch_size)
        database_path = runtime.settings.database_path
        metrics = _instrument_repository(runtime, enabled=profile_sql)
        application = runtime.application.void_material
        item_record_count = len(application._content().list("item", include_locked=False))

        async def sample_contract(enabled: bool) -> tuple[Any, ...]:
            application._item_alias_cache_enabled = enabled
            application._item_alias_cache = None
            results = []
            for request_number, adapter in enumerate(("onebot.v11", "qq.official")):
                normalized = _normalize(adapter, "perf-0000000", request_number, selected_commands[0])
                result = await runtime.adapters.dispatch(adapter, normalized.context, normalized.text)
                results.append(
                    (result.ok, result.code, result.message, result.data, result.retryable, result.actions)
                )
            return tuple(results)

        before_contract = await sample_contract(False)
        after_contract = await sample_contract(True)
        application._item_alias_cache_enabled = True
        application._item_alias_cache = None
        variants: dict[str, list[dict[str, Any]]] = {
            "before_linear_item_alias_scan": [],
            "after_bundle_item_alias_cache": [],
        }
        try:
            for level_index, concurrency in enumerate(levels):
                for repetition in range(2):
                    before_first = (level_index + repetition) % 2 == 0
                    order = (
                        (
                            ("before_linear_item_alias_scan", False),
                            ("after_bundle_item_alias_cache", True),
                        )
                        if before_first
                        else (
                            ("after_bundle_item_alias_cache", True),
                            ("before_linear_item_alias_scan", False),
                        )
                    )
                    for label, enabled in order:
                        application._item_alias_cache_enabled = enabled
                        application._item_alias_cache = None
                        started_builds = application._item_alias_cache_build_count
                        result = asdict(
                            await _measure(
                                runtime,
                                users,
                                concurrency,
                                total_requests,
                                metrics,
                                selected_commands,
                            )
                        )
                        result["repeat"] = repetition + 1
                        result["item_alias_cache_build_count"] = (
                            application._item_alias_cache_build_count - started_builds
                        )
                        variants[label].append(result)
        finally:
            application._item_alias_cache_enabled = True
            await runtime.close()

        db_bytes = _db_size(database_path)

        def report(results: list[dict[str, Any]]) -> dict[str, Any]:
            return {
                "users": users,
                "seed": seed,
                "item_record_count": item_record_count,
                "database_bytes_after_benchmark": db_bytes,
                "sql_profile_enabled": metrics is not None,
                "sql_profile_status": "collected" if metrics is not None else "not_collected",
                "levels": results,
                "errors": sum(int(item["errors"]) for item in results),
            }

        payload = {
            "comparison": {label: report(results) for label, results in variants.items()},
            "item_resolution_outputs_equivalent": before_contract == after_contract,
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


async def _run_companion_status_batch_comparison(
    users: int,
    batch_size: int,
    total_requests: int,
    levels: tuple[int, ...],
    *,
    profile_sql: bool | None = None,
) -> dict[str, Any]:
    """Compare per-companion gear reads with one indexed player-scoped read."""

    from nonebot_plugin_xiuxian_3.xiuxian.companions.models import CompanionView
    from nonebot_plugin_xiuxian_3.xiuxian.companions.rules import companion_definition
    from nonebot_plugin_xiuxian_3.xiuxian.utils.player import player_field

    temporary_path: Path
    with tempfile.TemporaryDirectory(prefix="xiuxian-perf-") as data_dir:
        temporary_path = Path(data_dir)
        runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11", "qq.official"))
        await runtime.initialize()
        seed = _seed_database(runtime, users, batch_size)
        path = runtime.settings.database_path
        companion_seed = _seed_companion_status_fixture(path, users)
        seed.update(companion_seed)
        seed["db_bytes"] = _db_size(path)
        with sqlite3.connect(path) as connection:
            explain = {
                "per_companion_gear": [
                    str(row[3])
                    for row in connection.execute(
                        "EXPLAIN QUERY PLAN SELECT gear_instance_id, gear_key, status, durability_bp "
                        "FROM companion_gear_instances WHERE companion_instance_id = ? "
                        "AND status = 'equipped' ORDER BY id",
                        (1,),
                    )
                ],
                "player_scoped_gear": [
                    str(row[3])
                    for row in connection.execute(
                        "EXPLAIN QUERY PLAN SELECT id, companion_instance_id, gear_instance_id, "
                        "gear_key, status, durability_bp FROM companion_gear_instances "
                        "WHERE player_id = ? AND status = 'equipped'",
                        (1,),
                    )
                ],
            }
        await asyncio.sleep(0.05)
        recovery_task = runtime._dispatch_recovery_task
        if recovery_task is not None:
            recovery_task.cancel()
            try:
                await recovery_task
            except asyncio.CancelledError:
                pass
            runtime._dispatch_recovery_task = None

        metrics = _instrument_repository(runtime, enabled=profile_sql)
        batch_view = runtime.repository._view_rows

        def legacy_view(connection: sqlite3.Connection, player_id: int) -> list[CompanionView]:
            rows = connection.execute(
                "SELECT * FROM companion_instances WHERE player_id = ? "
                "AND status <> 'retired' ORDER BY id",
                (player_id,),
            ).fetchall()
            result = []
            for row in rows:
                definition = companion_definition(
                    str(row["companion_key"]), getattr(runtime.repository, "content", None)
                )
                result.append(
                    CompanionView(
                        instance_id=str(row["instance_id"]),
                        companion_key=definition.key,
                        name=definition.label,
                        kind=definition.kind,
                        level=int(row["level"]),
                        experience=int(row["experience"]),
                        affinity=int(row["affinity"]),
                        stamina=int(row["stamina"]),
                        status=str(row["status"]),
                        deployed=bool(row["deployed"]),
                        evolution_stage=str(player_field(row, "evolution_stage", "base")),
                        skill_slots=int(player_field(row, "skill_slots", 0) or 0),
                        gear=tuple(runtime.repository._gear_snapshot(connection, int(row["id"]))),
                    )
                )
            return result

        def variant_view(view: Any) -> Any:
            if metrics is None:
                return view
            return _timed_callable(view, metrics["companion_status_view_ms"])

        def response_contract(result: Any) -> tuple[Any, ...]:
            return (
                result.ok,
                result.code,
                result.message,
                result.operation_id,
                result.data,
                result.retryable,
                result.actions,
            )

        async def status_pair() -> list[Any]:
            results = []
            for request_number, (adapter, user_id) in enumerate(
                (("onebot.v11", "perf-0000000"), ("qq.official", "perf-0000001"))
            ):
                normalized = _normalize(adapter, user_id, request_number, "灵兽状态")
                results.append(
                    await runtime.adapters.dispatch(adapter, normalized.context, normalized.text)
                )
            return results

        try:
            runtime.repository._view_rows = variant_view(legacy_view)
            before_equivalence = await status_pair()
            runtime.repository._view_rows = batch_view
            after_equivalence = await status_pair()
            outputs_equivalent = tuple(map(response_contract, before_equivalence)) == tuple(
                map(response_contract, after_equivalence)
            )
            if not outputs_equivalent:
                raise AssertionError("灵兽状态 response differs between per-companion and batched reads")

            variants: dict[str, list[dict[str, Any]]] = {
                "before_per_companion_reads": [],
                "after_indexed_player_batch": [],
            }
            commands = ("灵兽状态",)
            for level_index, concurrency in enumerate(levels):
                for repetition in range(2):
                    before_first = (level_index + repetition) % 2 == 0
                    order = (
                        (
                            ("before_per_companion_reads", legacy_view),
                            ("after_indexed_player_batch", batch_view.__wrapped__
                             if hasattr(batch_view, "__wrapped__") else batch_view),
                        )
                        if before_first
                        else (
                            ("after_indexed_player_batch", batch_view.__wrapped__
                             if hasattr(batch_view, "__wrapped__") else batch_view),
                            ("before_per_companion_reads", legacy_view),
                        )
                    )
                    for label, view in order:
                        runtime.repository._view_rows = variant_view(view)
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
            runtime.repository._view_rows = batch_view
            await runtime.close()

        db_bytes = _db_size(path)

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
            "status_outputs_equivalent": outputs_equivalent,
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
        "--compare-arena-season-events",
        action="store_true",
        help="compare separate vs shared season history reads on one fixture",
    )
    compare.add_argument(
        "--compare-arena-season-cache",
        action="store_true",
        help="compare repeated season history work with the per-connection cache",
    )
    compare.add_argument(
        "--compare-arena-season-index",
        action="store_true",
        help="compare a covering season-history index on one fixture",
    )
    compare.add_argument(
        "--compare-arena-season-top-n",
        action="store_true",
        help="compare full ranking sorts with top-N selection on one arena fixture",
    )
    compare.add_argument(
        "--compare-player-stats-formula-cache",
        action="store_true",
        help="compare uncached and repository-scoped stats formula reuse on one fixture",
    )
    compare.add_argument(
        "--compare-player-profile-projection",
        action="store_true",
        help="compare repeated versus shared player normalization on one profile fixture",
    )
    compare.add_argument(
        "--compare-equipment-definition-cache",
        action="store_true",
        help="compare repeated equipment catalogue validation with bundle reuse",
    )
    compare.add_argument(
        "--compare-void-material-item-cache",
        action="store_true",
        help="compare linear void-material item alias scans with bundle reuse",
    )
    compare.add_argument(
        "--compare-companion-status-batch",
        action="store_true",
        help="compare per-companion and indexed player-scoped gear reads",
    )
    compare.add_argument(
        "--compare-idle-preview-state",
        action="store_true",
        help="compare repeated vs shared route state on one idle-preview fixture",
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
        choices=(
            "我的状态",
            "挂机状态",
            "挂机预览",
            "主线状态",
            "移动预览 玄天近郊",
            "竞技场赛季",
            "寄售物资 虚空晶体 1 100",
            "法器预览",
            "重铸预览",
            "灵兽状态",
        ),
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
    if args.compare_arena_season_top_n:
        payload = asyncio.run(
            _run_arena_season_top_n_comparison(
                args.users,
                args.batch_size,
                args.requests,
                levels,
                profile_sql=profile_sql,
                commands=commands,
            )
        )
    elif args.compare_player_stats_formula_cache:
        payload = asyncio.run(
            _run_player_stats_formula_cache_comparison(
                args.users,
                args.batch_size,
                args.requests,
                levels,
                profile_sql=profile_sql,
                commands=commands,
            )
        )
    elif args.compare_player_profile_projection:
        payload = asyncio.run(
            _run_player_profile_projection_comparison(
                args.users,
                args.batch_size,
                args.requests,
                levels,
                profile_sql=profile_sql,
                commands=commands,
            )
        )
    elif args.compare_equipment_definition_cache:
        payload = asyncio.run(
            _run_equipment_definition_cache_comparison(
                args.users,
                args.batch_size,
                args.requests,
                levels,
                profile_sql=profile_sql,
                commands=commands,
            )
        )
    elif args.compare_void_material_item_cache:
        payload = asyncio.run(
            _run_void_material_item_cache_comparison(
                args.users,
                args.batch_size,
                args.requests,
                levels,
                profile_sql=profile_sql,
                commands=commands,
            )
        )
    elif args.compare_companion_status_batch:
        payload = asyncio.run(
            _run_companion_status_batch_comparison(
                args.users,
                args.batch_size,
                args.requests,
                levels,
                profile_sql=profile_sql,
            )
        )
    elif args.compare_idle_preview_state:
        payload = asyncio.run(
            _run_idle_preview_comparison(
                args.users,
                args.batch_size,
                args.requests,
                levels,
                profile_sql=profile_sql,
                commands=commands,
            )
        )
    elif args.compare_arena_season_index:
        payload = asyncio.run(
            _run_arena_season_index_comparison(
                args.users,
                args.batch_size,
                args.requests,
                levels,
                profile_sql=profile_sql,
                commands=commands,
            )
        )
    elif args.compare_arena_season_events:
        payload = asyncio.run(
            _run_arena_season_event_comparison(
                args.users,
                args.batch_size,
                args.requests,
                levels,
                profile_sql=profile_sql,
                commands=commands,
            )
        )
    elif args.compare_arena_season_cache:
        payload = asyncio.run(
            _run_arena_season_cache_comparison(
                args.users,
                args.batch_size,
                args.requests,
                levels,
                profile_sql=profile_sql,
                commands=commands,
            )
        )
    elif args.compare_connection_probe:
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
