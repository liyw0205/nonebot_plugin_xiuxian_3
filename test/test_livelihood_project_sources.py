from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


async def _create_player(runtime, adapter: str, user: str) -> None:
    assert (await runtime.dispatch(_context(adapter, user, f"{user}:create"), "开始修仙")).ok
    assert (await runtime.dispatch(_context(adapter, user, f"{user}:seek"), "寻仙问道")).ok


def test_project_service_sources_are_real_owned_and_single_use_on_both_adapters() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 10, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            recovery_source: tuple[str, str, str] | None = None
            for adapter in ("qq.official", "onebot.v11"):
                user = f"service-{adapter}"
                await _create_player(runtime, adapter, user)
                with runtime.repository._connect() as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?",
                        (adapter, user),
                    ).fetchone()[0]
                    connection.execute(
                        "UPDATE players SET location_key = 'xuantian.new_town', stamina = 10, pollution = 40, "
                        "inventory_json = ?, faction_reputation_json = ? WHERE id = ?",
                        (
                            json.dumps(
                                {
                                    "item.food.coarse_spirit_rice": 3,
                                    "item.pill.soul_restore": 1,
                                },
                                sort_keys=True,
                            ),
                            json.dumps({"demon": 300, "beast": 300}, sort_keys=True),
                            player_id,
                        ),
                    )
                    connection.execute(
                        "INSERT INTO activity_events(player_id, event_key, source_operation_id, occurred_at, payload_json) "
                        "VALUES (?, ?, ?, ?, '{}')",
                        (player_id, "access.project.domain_refuge", f"access-{adapter}", clock().isoformat()),
                    )
                    connection.execute(
                        "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            f"malformed-source-{adapter}",
                            "livelihood.settle_route",
                            player_id,
                            "",
                            "not-json",
                            clock().isoformat(),
                        ),
                    )
                    connection.execute(
                        "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            f"array-source-{adapter}",
                            "livelihood.settle_route",
                            player_id,
                            "",
                            "[]",
                            clock().isoformat(),
                        ),
                    )

                malformed_before = await runtime.dispatch(
                    _context(adapter, user, f"{user}:malformed-project-before"),
                    "公共项目",
                )
                assert malformed_before.code == "PROJECT_LIST"
                malformed_project = next(
                    project for project in malformed_before.data["projects"] if project["project_key"] == "project.domain_refuge"
                )
                malformed_attempt = await runtime.dispatch(
                    _context(adapter, user, f"{user}:malformed-project"),
                    f"贡献公共项目 project.domain_refuge 运输 malformed-source-{adapter}",
                )
                assert malformed_attempt.code == "PROJECT_SOURCE_INVALID"
                array_attempt = await runtime.dispatch(
                    _context(adapter, user, f"{user}:array-project"),
                    f"贡献公共项目 project.domain_refuge 运输 array-source-{adapter}",
                )
                assert array_attempt.code == "PROJECT_SOURCE_INVALID"
                malformed_after = await runtime.dispatch(
                    _context(adapter, user, f"{user}:malformed-project-after"),
                    "公共项目",
                )
                assert malformed_after.code == "PROJECT_LIST"
                unchanged_project = next(
                    project for project in malformed_after.data["projects"] if project["project_key"] == "project.domain_refuge"
                )
                assert unchanged_project["contribution_points"] == malformed_project["contribution_points"]

                started = await runtime.dispatch(
                    _context(adapter, user, f"{user}:route-start"),
                    "开始运输 粗糙灵米",
                )
                assert started.code == "ROUTE_STARTED"
                clock.advance(minutes=20)
                route = await runtime.dispatch(
                    _context(adapter, user, f"{user}:route-settle"),
                    "结算运输",
                )
                assert route.code == "ROUTE_SETTLED"
                route_source = route.operation_id
                contribution = await runtime.dispatch(
                    _context(adapter, user, f"{user}:route-project"),
                    f"贡献公共项目 project.domain_refuge 运输 {route_source}",
                )
                assert contribution.code == "PROJECT_CONTRIBUTED"
                assert contribution.data["service_key"] == "service.transport"
                assert contribution.data["contribution_points"] == 20

                same_operation = await runtime.dispatch(
                    _context(adapter, user, f"{user}:route-project"),
                    f"贡献公共项目 project.domain_refuge 运输 {route_source}",
                )
                assert same_operation.code == "PROJECT_CONTRIBUTED"
                assert same_operation.data["idempotent_replay"] is True

                replay_source = await runtime.dispatch(
                    _context(adapter, user, f"{user}:route-project-replay"),
                    f"贡献公共项目 project.domain_refuge 运输 {route_source}",
                )
                assert replay_source.code == "PROJECT_SOURCE_ALREADY_USED"

                purify = await runtime.dispatch(
                    _context(adapter, user, f"{user}:purify"),
                    "净化污染",
                )
                assert purify.code == "POLLUTION_PURIFIED"
                purification = await runtime.dispatch(
                    _context(adapter, user, f"{user}:purify-project"),
                    f"贡献公共项目 project.abyss_purification 净化 {purify.operation_id}",
                )
                assert purification.code == "PROJECT_CONTRIBUTED"
                assert purification.data["service_key"] == "service.purification"
                assert purification.data["contribution_points"] == 15

                with runtime.repository._connect() as connection:
                    connection.execute(
                        "UPDATE players SET location_key = 'xuantian.outskirts' WHERE id = ?",
                        (player_id,),
                    )
                bonded = await runtime.dispatch(
                    _context(adapter, user, f"{user}:bond"),
                    "结缘灵兽 beast.wood_rat",
                )
                assert bonded.code == "COMPANION_BONDED"
                fed = await runtime.dispatch(
                    _context(adapter, user, f"{user}:feed"),
                    f"喂养灵兽 {bonded.data['instance_id']}",
                )
                assert fed.code == "COMPANION_FED"
                with runtime.repository._connect() as connection:
                    before_service_assets = connection.execute(
                        "SELECT spirit_stones, stamina, energy, inventory_json FROM players WHERE id = ?",
                        (player_id,),
                    ).fetchone()
                companion = await runtime.dispatch(
                    _context(adapter, user, f"{user}:companion-project"),
                    f"贡献公共项目 project.ancestral_habitat 驯养 {fed.operation_id}",
                )
                assert companion.code == "PROJECT_CONTRIBUTED"
                assert companion.data["service_key"] == "service.taming"
                assert companion.data["contribution_points"] == 15

                with runtime.repository._connect() as connection:
                    connection.execute(
                        "UPDATE companion_instances SET status = 'injured', injury_until = ? WHERE instance_id = ?",
                        (clock().isoformat(), bonded.data["instance_id"]),
                    )
                rested = await runtime.dispatch(
                    _context(adapter, user, f"{user}:rest"),
                    f"休养灵兽 {bonded.data['instance_id']}",
                )
                assert rested.code == "COMPANION_RESTED"
                with runtime.repository._connect() as connection:
                    connection.execute(
                        "UPDATE companion_instances SET status = 'injured', injury_until = ? WHERE instance_id = ?",
                        (clock().isoformat(), bonded.data["instance_id"]),
                    )
                repaired = await runtime.dispatch(
                    _context(adapter, user, f"{user}:repair-project"),
                    f"贡献公共项目 project.ancestral_habitat 修复 {rested.operation_id}",
                )
                assert repaired.code == "PROJECT_CONTRIBUTED"
                assert repaired.data["service_key"] == "service.repair"
                assert repaired.data["contribution_points"] == 15
                with runtime.repository._connect() as connection:
                    after_service_assets = connection.execute(
                        "SELECT spirit_stones, stamina, energy, inventory_json FROM players WHERE id = ?",
                        (player_id,),
                    ).fetchone()
                    assert tuple(after_service_assets) == tuple(before_service_assets)

                if recovery_source is None:
                    recovery_source = (adapter, user, route_source)

                with runtime.repository._connect() as connection:
                    row = connection.execute(
                        "SELECT contribution_kind, source_operation_id, service_key, quantity "
                        "FROM livelihood_project_contributions WHERE operation_id = ?",
                        (f"{user}:route-project",),
                    ).fetchone()
                    assert tuple(row) == ("service", route_source, "service.transport", 1)
                    cultivation = connection.execute(
                        "SELECT cultivation, total_cultivation FROM players WHERE id = ?",
                        (player_id,),
                    ).fetchone()
                    assert tuple(cultivation) == (0, 0)

            assert recovery_source is not None
            await runtime.close()
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user, route_source = recovery_source
            recovered = await runtime.dispatch(
                _context(adapter, user, f"{user}:route-project"),
                f"贡献公共项目 project.domain_refuge 运输 {route_source}",
            )
            assert recovered.code == "PROJECT_CONTRIBUTED"
            assert recovered.data["idempotent_replay"] is True

            with runtime.repository._connect() as connection:
                source = connection.execute(
                    "SELECT source_operation_id FROM livelihood_project_contributions "
                    "WHERE service_key = 'service.transport' LIMIT 1"
                ).fetchone()[0]
            other = "service-other"
            await _create_player(runtime, "onebot.v11", other)
            with runtime.repository._connect() as connection:
                other_id = connection.execute(
                    "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?",
                    ("onebot.v11", other),
                ).fetchone()[0]
                connection.execute(
                    "UPDATE players SET faction_reputation_json = ? WHERE id = ?",
                    (json.dumps({"demon": 300}, sort_keys=True), other_id),
                )
                connection.execute(
                    "INSERT INTO activity_events(player_id, event_key, source_operation_id, occurred_at, payload_json) "
                    "VALUES (?, ?, ?, ?, '{}')",
                    (other_id, "access.project.domain_refuge", "other-access", clock().isoformat()),
                )
            await runtime.dispatch(_context("onebot.v11", other, "other:list"), "公共项目")
            rejected = await runtime.dispatch(
                _context("onebot.v11", other, "other:foreign"),
                f"贡献公共项目 project.domain_refuge 运输 {source}",
            )
            assert rejected.code == "PROJECT_SOURCE_INVALID"
            await runtime.close()

    asyncio.run(run())


def test_project_service_source_rejects_malformed_operation_json_without_contribution() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter = "onebot.v11"
            user = "service-malformed"
            await _create_player(runtime, adapter, user)
            with runtime.repository._connect() as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?",
                    (adapter, user),
                ).fetchone()[0]
                connection.execute(
                    "UPDATE players SET faction_reputation_json = ? WHERE id = ?",
                    (json.dumps({"demon": 300}, sort_keys=True), player_id),
                )
                connection.execute(
                    "INSERT INTO activity_events(player_id, event_key, source_operation_id, occurred_at, payload_json) "
                    "VALUES (?, ?, ?, ?, '{}')",
                    (player_id, "access.project.abyss_purification", "malformed-access", runtime.repository._now().isoformat()),
                )
                connection.execute(
                    "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) "
                    "VALUES (?, ?, ?, '', ?, ?)",
                    (
                        "malformed-source",
                        "production.purify_pollution",
                        player_id,
                        "{not-json",
                        runtime.repository._now().isoformat(),
                    ),
                )
                request_hash = runtime.repository._request_hash(
                    "livelihood.contribute_project",
                    {
                        "platform": adapter,
                        "platform_user_id": user,
                        "project_key": "project.abyss_purification",
                        "resource_key": "",
                        "amount": 0,
                        "source_operation_id": "malformed-source",
                    },
                )
                connection.execute(
                    "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        "malformed-project-json",
                        "livelihood.contribute_project",
                        player_id,
                        request_hash,
                        "[]",
                        runtime.repository._now().isoformat(),
                    ),
                )

            rejected = await runtime.dispatch(
                _context(adapter, user, "malformed-project"),
                "贡献公共项目 project.abyss_purification 净化 malformed-source",
            )
            assert rejected.code == "PROJECT_SOURCE_INVALID"
            conflict = await runtime.dispatch(
                _context(adapter, user, "malformed-project-json"),
                "贡献公共项目 project.abyss_purification 净化 malformed-source",
            )
            assert conflict.code == "OPERATION_CONFLICT"
            with runtime.repository._connect() as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM livelihood_project_contributions WHERE player_id = ?",
                    (player_id,),
                ).fetchone()[0] == 0
            await runtime.close()

    asyncio.run(run())
