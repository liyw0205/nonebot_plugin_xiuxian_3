from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.xiuxian.persistence.errors import BountyIncompleteError
from nonebot_plugin_xiuxian_3.runtime import create_runtime

BOUNTY = "bounty.dao_origin_service"


def _context(user: str, operation: str = "") -> CommandContext:
    return CommandContext(adapter="onebot.v11", user_id=user, operation_id=operation)


async def _send(runtime, user: str, text: str):
    return await runtime.adapters.dispatch("onebot.v11", _context(user), text)


async def _create(runtime, user: str) -> int:
    assert (await _send(runtime, user, "开始修仙")).ok
    assert (await _send(runtime, user, "寻仙问道")).ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='dao_union', realm_layer=1 "
            "WHERE platform='onebot.v11' AND platform_user_id=?",
            (user,),
        )
        return int(
            connection.execute(
                "SELECT id FROM players WHERE platform='onebot.v11' AND platform_user_id=?", (user,)
            ).fetchone()[0]
        )


def _service(
    runtime,
    player_id: int,
    *,
    project_key: str,
    index: int,
    kind: str = "service",
    when: str = "2026-11-03T05:00:01+00:00",
) -> None:
    """Record one public-project contribution of the requested kind."""

    with sqlite3.connect(runtime.settings.database_path) as connection:
        # One row per (project_key, business_week); extra contributions attach to it.
        project_id = f"proj-{project_key}"
        connection.execute(
            "INSERT OR IGNORE INTO livelihood_projects(project_id, project_key, business_week, "
            "status, target_points, contribution_points, effect_key, created_at, updated_at) "
            "VALUES (?, ?, '2026-W45', 'active', 10, 3, 'effect.town', "
            "'2026-11-03T05:00:00+00:00', '2026-11-03T05:00:00+00:00')",
            (project_id, project_key),
        )
        connection.execute(
            "INSERT INTO livelihood_project_contributions(contribution_id, project_id, player_id, "
            "operation_id, source_operation_id, contribution_kind, service_key, quantity, "
            "resource_key, resource_amount, contribution_points, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'service.town_help', 1, 'service.town_help', 1, 3, ?)",
            (f"c-{project_key}-{index}", project_id, player_id, f"op-{project_key}-{index}", f"src-{project_key}-{index}", kind, when),
        )


def _progress(runtime, key: str = BOUNTY):
    async def _inner():
        board = await runtime.repository.get_bounty_board(
            platform="onebot.v11", platform_user_id="a"
        )
        for offer in board.offers:
            if offer.key == key:
                return offer.progress, offer.target
        return None, None

    return _inner()


def test_service_bounty_counts_distinct_public_projects_only() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(
                data_dir=data_dir, clock=lambda: datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc)
            )
            try:
                player_id = await _create(runtime, "a")

                # Contributions made before accepting must not count.
                _service(
                    runtime,
                    player_id,
                    project_key="project.town_well",
                    index=0,
                    when="2026-11-03T04:00:00+00:00",
                )
                accepted = await runtime.repository.accept_bounty(
                    platform="onebot.v11",
                    platform_user_id="a",
                    bounty_key=BOUNTY,
                    operation_id="ab-1",
                )
                assert accepted.bounty_key == BOUNTY
                assert accepted.target == 3
                assert accepted.progress == 0

                progress, target = await _progress(runtime)
                assert (progress, target) == (0, 3)

                # A resource contribution is not a service.
                _service(runtime, player_id, project_key="project.market_road", index=1, kind="resource")
                progress, _ = await _progress(runtime)
                assert progress == 0

                # The same project twice still counts once.
                _service(runtime, player_id, project_key="project.herb_garden", index=2)
                _service(runtime, player_id, project_key="project.herb_garden", index=3)
                progress, _ = await _progress(runtime)
                assert progress == 1

                _service(runtime, player_id, project_key="project.town_well", index=4)
                _service(runtime, player_id, project_key="project.domain_refuge", index=5)
                progress, target = await _progress(runtime)
                assert (progress, target) == (3, 3)
            finally:
                await runtime.close()

    asyncio.run(run())


def test_claim_requires_the_three_services_and_then_pays_once() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(
                data_dir=data_dir, clock=lambda: datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc)
            )
            try:
                player_id = await _create(runtime, "a")
                await runtime.repository.accept_bounty(
                    platform="onebot.v11",
                    platform_user_id="a",
                    bounty_key=BOUNTY,
                    operation_id="ab-1",
                )
                # An incomplete target is refused outright, not silently paid.
                try:
                    await runtime.repository.claim_bounty(
                        platform="onebot.v11", platform_user_id="a", operation_id="cl-early"
                    )
                except BountyIncompleteError:
                    pass
                else:  # pragma: no cover - 必须是拒绝
                    raise AssertionError("an incomplete bounty must not be claimable")

                for index, project_key in enumerate(
                    ("project.town_well", "project.market_road", "project.herb_garden"), start=1
                ):
                    _service(runtime, player_id, project_key=project_key, index=index)

                claimed = await runtime.repository.claim_bounty(
                    platform="onebot.v11", platform_user_id="a", operation_id="cl-1"
                )
                assert claimed.status == "claimed"
                replay = await runtime.repository.claim_bounty(
                    platform="onebot.v11", platform_user_id="a", operation_id="cl-1"
                )
                assert replay.already_completed is True
            finally:
                await runtime.close()

    asyncio.run(run())


def test_rejects_other_realms() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(
                data_dir=data_dir, clock=lambda: datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc)
            )
            try:
                assert (await _send(runtime, "low", "开始修仙")).ok
                assert (await _send(runtime, "low", "寻仙问道")).ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET stage='cultivator', realm_key='nascent_soul', "
                        "realm_layer=9 WHERE platform_user_id='low'"
                    )
                try:
                    await runtime.repository.accept_bounty(
                        platform="onebot.v11",
                        platform_user_id="low",
                        bounty_key=BOUNTY,
                        operation_id="ab-low",
                    )
                except Exception as exc:  # noqa: BLE001 - the error type is the assertion
                    assert "requirement" in str(exc).lower() or "realm" in str(exc).lower()
                else:  # pragma: no cover -必须是拒绝
                    raise AssertionError("a lower realm must not accept the dao-origin bounty")
            finally:
                await runtime.close()

    asyncio.run(run())