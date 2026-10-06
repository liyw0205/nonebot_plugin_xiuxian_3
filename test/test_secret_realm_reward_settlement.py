from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from combat_fixtures import equip_damage_weapon
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


ADAPTERS = ("qq.official", "onebot.v11")
LOCAL_KEY = "local.xuantian.new_town"


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


def _copy_content(data_dir: Path) -> None:
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)


def _set_location_cap(data_dir: Path, cap: int) -> None:
    path = data_dir / "地图" / "地点.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    location = next(row for row in document["records"] if row["key"] == "xuantian.new_town")
    location["local_reputation_maximum"] = cap
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def _create_and_seek(runtime, adapter: str, user: str) -> None:
    assert (await runtime.adapters.dispatch(adapter, _context(adapter, user, f"{user}:create"), "开始修仙")).ok
    assert (await runtime.adapters.dispatch(adapter, _context(adapter, user, f"{user}:seek"), "寻仙问道")).ok


def _prepare_player(
    runtime,
    adapter: str,
    user: str,
    *,
    instance: str,
    reputation: int = 0,
) -> None:
    if instance == "spring":
        realm, layer, location, inventory = "qi_sensing", 3, "xuantian.spirit_field", {}
    else:
        realm, layer, location, inventory = (
            "golden_core",
            1,
            "xuantian.floating_boat",
            {"item.ticket.cloud_boat_fragment": 1},
        )
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key=?, realm_layer=?, location_key=?, "
            "stamina=100, stamina_max=100, max_hp=5000, initiative=100, "
            "inventory_json=? WHERE platform=? AND platform_user_id=?",
            (
                realm,
                layer,
                location,
                json.dumps(inventory),
                adapter,
                user,
            ),
        )
        if reputation:
            player_id = connection.execute(
                "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at) "
                "VALUES (?, ?, 0, 'test')",
                (player_id, json.dumps({LOCAL_KEY: reputation})),
            )
    equip_damage_weapon(runtime, adapter, user, 500)


async def _clear(runtime, adapter: str, user: str, prefix: str, realm: str) -> None:
    name = "灵泉小径" if realm == "spring" else "云舟秘境"
    entered = await runtime.adapters.dispatch(
        adapter, _context(adapter, user, f"{prefix}:enter"), f"进入秘境 {name}"
    )
    assert entered.code == "SECRET_REALM_ENTERED"
    assert (
        await runtime.adapters.dispatch(
            adapter, _context(adapter, user, f"{prefix}:resource"), "选择秘境节点 资源"
        )
    ).ok
    assert (
        await runtime.adapters.dispatch(
            adapter, _context(adapter, user, f"{prefix}:encounter"), "选择秘境节点 遭遇"
        )
    ).code == "SECRET_REALM_COMBAT_PENDING"
    progress = await runtime.adapters.dispatch(
        adapter, _context(adapter, user, f"{prefix}:combat"), "结算秘境"
    )
    if realm == "boat":
        assert progress.data["current_node"] == "choice"
        assert (
            await runtime.adapters.dispatch(
                adapter, _context(adapter, user, f"{prefix}:choice"), "选择秘境节点 选择"
            )
        ).data["status"] == "cleared"
    else:
        assert progress.data["status"] == "cleared"


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize(
    ("starting_reputation", "expected_reputation", "expected_reward_reputation"),
    ((4, 6, 2), (8, 8, 0)),
)
def test_secret_realm_freezes_reputation_cap_and_replays_after_restart(
    adapter: str,
    starting_reputation: int,
    expected_reputation: int,
    expected_reward_reputation: int,
) -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            _copy_content(data_dir)
            _set_location_cap(data_dir, 6)
            user = f"{adapter}:secret-cap"
            runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
            await _create_and_seek(runtime, adapter, user)
            _prepare_player(
                runtime, adapter, user, instance="spring", reputation=starting_reputation
            )
            entered = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "cap:enter"), "进入秘境 灵泉小径"
            )
            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot_raw = connection.execute(
                    "SELECT snapshot_json FROM secret_realm_runs WHERE run_id=?",
                    (entered.data["run_id"],),
                ).fetchone()[0]
            snapshot = json.loads(snapshot_raw)
            assert snapshot["local_reputation_key"] == LOCAL_KEY
            assert snapshot["local_reputation_maximum"] == 6
            assert (
                await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "cap:resource"), "选择秘境节点 资源"
                )
            ).ok
            assert (
                await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "cap:encounter"), "选择秘境节点 遭遇"
                )
            ).code == "SECRET_REALM_COMBAT_PENDING"
            await runtime.close()

            _set_location_cap(data_dir, 20)
            recovered = create_runtime(data_dir=data_dir, adapters=(adapter,))
            try:
                settled = await recovered.adapters.dispatch(
                    adapter, _context(adapter, user, "cap:combat"), "结算秘境"
                )
                assert settled.data["status"] == "settled"
                assert settled.data["reward"] == {
                    "item.herb.spirit_leaf": 2,
                    LOCAL_KEY: expected_reward_reputation,
                }
                await recovered.close()

                replay_runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
                try:
                    replay = await replay_runtime.adapters.dispatch(
                        adapter, _context(adapter, user, "cap:combat"), "结算秘境"
                    )
                    assert replay.data["idempotent_replay"] is True
                    assert replay.data["reward"] == settled.data["reward"]
                    with sqlite3.connect(replay_runtime.settings.database_path) as connection:
                        inventory, local_json, operation_count = connection.execute(
                            "SELECT p.inventory_json, r.local_json, "
                            "(SELECT COUNT(*) FROM operations WHERE operation_id='cap:combat') "
                            "FROM players p JOIN player_reputations r ON r.player_id=p.id "
                            "WHERE p.platform=? AND p.platform_user_id=?",
                            (adapter, user),
                        ).fetchone()
                    assert json.loads(inventory)["item.herb.spirit_leaf"] == 2
                    assert json.loads(local_json)[LOCAL_KEY] == expected_reputation
                    assert operation_count == 1
                finally:
                    await replay_runtime.close()
            except Exception:
                await recovered.close()
                raise

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_secret_realm_codex_and_assets_roll_back_when_operation_insert_fails(adapter: str) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
            user = f"{adapter}:secret-rollback"
            await _create_and_seek(runtime, adapter, user)
            _prepare_player(runtime, adapter, user, instance="boat", reputation=999)
            await _clear(runtime, adapter, user, "rollback", "boat")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "CREATE TRIGGER fail_secret_settlement BEFORE INSERT ON operations "
                    "WHEN NEW.operation_id='rollback:settle' "
                    "BEGIN SELECT RAISE(ABORT, 'injected operation failure'); END"
                )
            failed = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "rollback:settle"), "结算秘境"
            )
            assert failed.code == "PERSISTENCE_ERROR"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                status, inventory, reputation, codex_count, operation_count = connection.execute(
                    "SELECT r.status, p.inventory_json, pr.local_json, "
                    "(SELECT COUNT(*) FROM codex_entries c WHERE c.player_id=p.id "
                    "AND c.entry_key='codex.instance.cloud_boat'), "
                    "(SELECT COUNT(*) FROM operations o WHERE o.operation_id='rollback:settle') "
                    "FROM secret_realm_runs r JOIN players p ON p.id=r.player_id "
                    "JOIN player_reputations pr ON pr.player_id=p.id "
                    "WHERE p.platform=? AND p.platform_user_id=?",
                    (adapter, user),
                ).fetchone()
                connection.execute("DROP TRIGGER fail_secret_settlement")
            assert status == "cleared"
            assert json.loads(inventory).get("item.ticket.cloud_boat_fragment", 0) == 0
            assert json.loads(reputation)[LOCAL_KEY] == 999
            assert codex_count == operation_count == 0

            settled = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "rollback:settle"), "结算秘境"
            )
            assert settled.code == "SECRET_REALM_SETTLED"
            assert settled.data["reward"] == {"codex.instance.cloud_boat": 1, LOCAL_KEY: 1}
            replay = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "rollback:settle"), "结算秘境"
            )
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory, reputation, codex_count, stale_codex_inventory = connection.execute(
                    "SELECT p.inventory_json, pr.local_json, "
                    "(SELECT COUNT(*) FROM codex_entries c WHERE c.player_id=p.id "
                    "AND c.entry_key='codex.instance.cloud_boat'), "
                    "json_extract(p.inventory_json, '$.codex.instance.cloud_boat') "
                    "FROM players p JOIN player_reputations pr ON pr.player_id=p.id "
                    "WHERE p.platform=? AND p.platform_user_id=?",
                    (adapter, user),
                ).fetchone()
            assert json.loads(inventory).get("item.ticket.cloud_boat_fragment", 0) == 0
            assert json.loads(reputation)[LOCAL_KEY] == 1000
            assert codex_count == 1
            assert stale_codex_inventory is None
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_secret_realm_bad_reputation_json_rolls_back_and_same_operation_retries(
    adapter: str,
) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
            user = f"{adapter}:secret-bad-json"
            await _create_and_seek(runtime, adapter, user)
            _prepare_player(runtime, adapter, user, instance="boat")
            await _clear(runtime, adapter, user, "bad-json", "boat")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
                ).fetchone()[0]
                connection.execute(
                    "INSERT INTO player_reputations(player_id, local_json, updated_at) VALUES (?, '{', 'test')",
                    (player_id,),
                )
            failed = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "bad-json:settle"), "结算秘境"
            )
            assert failed.code == "PERSISTENCE_ERROR"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                status, inventory, operation_count = connection.execute(
                    "SELECT r.status, p.inventory_json, "
                    "(SELECT COUNT(*) FROM operations WHERE operation_id='bad-json:settle') "
                    "FROM secret_realm_runs r JOIN players p ON p.id=r.player_id WHERE p.id=?",
                    (player_id,),
                ).fetchone()
                connection.execute(
                    "UPDATE player_reputations SET local_json='{}' WHERE player_id=?", (player_id,)
                )
            assert status == "cleared"
            assert json.loads(inventory).get("item.herb.spirit_leaf", 0) == 0
            assert operation_count == 0
            settled = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "bad-json:settle"), "结算秘境"
            )
            assert settled.code == "SECRET_REALM_SETTLED"
            assert settled.data["reward"][LOCAL_KEY] == 12
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize(
    "damaged_field", ("codex_categories", "local_reputation_key", "local_reputation_maximum")
)
def test_secret_realm_bad_reward_snapshot_rolls_back_and_same_operation_retries(
    adapter: str, damaged_field: str,
) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
            user = f"{adapter}:secret-bad-snapshot"
            await _create_and_seek(runtime, adapter, user)
            _prepare_player(runtime, adapter, user, instance="boat")
            await _clear(runtime, adapter, user, "bad-snapshot", "boat")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id, snapshot_raw = connection.execute(
                    "SELECT p.id, r.snapshot_json FROM secret_realm_runs r "
                    "JOIN players p ON p.id=r.player_id "
                    "WHERE p.platform=? AND p.platform_user_id=?",
                    (adapter, user),
                ).fetchone()
                snapshot = json.loads(snapshot_raw)
                if damaged_field == "codex_categories":
                    snapshot["codex_categories"]["codex.instance.cloud_boat"] = ""
                elif damaged_field == "local_reputation_key":
                    snapshot[damaged_field] = None
                else:
                    snapshot[damaged_field] = True
                connection.execute(
                    "UPDATE secret_realm_runs SET snapshot_json=? WHERE player_id=?",
                    (json.dumps(snapshot), player_id),
                )

            failed = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "bad-snapshot:settle"), "结算秘境"
            )
            assert failed.code == "PERSISTENCE_ERROR"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                status, inventory, local_json, codex_count, operation_count = connection.execute(
                    "SELECT r.status, p.inventory_json, pr.local_json, "
                    "(SELECT COUNT(*) FROM codex_entries c WHERE c.player_id=p.id "
                    "AND c.entry_key='codex.instance.cloud_boat'), "
                    "(SELECT COUNT(*) FROM operations WHERE operation_id='bad-snapshot:settle') "
                    "FROM secret_realm_runs r JOIN players p ON p.id=r.player_id "
                    "LEFT JOIN player_reputations pr ON pr.player_id=p.id WHERE p.id=?",
                    (player_id,),
                ).fetchone()
                original = json.loads(snapshot_raw)
                connection.execute(
                    "UPDATE secret_realm_runs SET snapshot_json=? WHERE player_id=?",
                    (json.dumps(original), player_id),
                )
            assert status == "cleared"
            assert json.loads(inventory).get("item.ticket.cloud_boat_fragment", 0) == 0
            assert not local_json or json.loads(local_json).get(LOCAL_KEY, 0) == 0
            assert codex_count == operation_count == 0

            settled = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "bad-snapshot:settle"), "结算秘境"
            )
            assert settled.code == "SECRET_REALM_SETTLED"
            assert settled.data["reward"] == {"codex.instance.cloud_boat": 1, LOCAL_KEY: 12}
            await runtime.close()

    asyncio.run(run())
