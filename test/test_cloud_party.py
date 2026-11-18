from __future__ import annotations

import asyncio
import json

import pytest

from combat_fixtures import equip_damage_weapon
from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.combat_content import validate_combat_content
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.content_integrity import validate_source_content
from nonebot_plugin_xiuxian_3.xiuxian.repository import OperationConflictError, PartyBattleBusyError
from test_companion_old_trail_mainline import _database_state
from test_mainline_vertical_slice import MutableClock, _copy_content


ENEMY = "enemy.cloud_boat_guardian"
IRON = "item.material.cloud_iron"
SAND = "item.mat.array_sand"
REWARD = {"cultivation": 100, "spirit_stones": 40, IRON: 1, SAND: 1}


class Team:
    def __init__(self, data, *, leader_adapter="qq.official", size=4):
        self.data = data
        self.clock = MutableClock()
        self.runtime = create_runtime(data_dir=data, clock=self.clock)
        other = "onebot.v11" if leader_adapter == "qq.official" else "qq.official"
        self.members = tuple((leader_adapter if index % 2 == 0 else other, f"sailor-{index}") for index in range(size))
        self.sequence = 0

    async def send(self, text, operation="", member=0, *, writable=True):
        self.sequence += 1
        adapter, user = self.members[member]
        return await self.runtime.dispatch(CommandContext(
            adapter=adapter, user_id=user, nickname=user, operation_id=operation or f"sail-{self.sequence}",
            can_write_assets=writable, capabilities=("text", "markdown", "keyboard"),
        ), text)

    async def prepare(self, *, party_command="创建多人副本队伍", confirm=True, damage=1000):
        for index, (adapter, user) in enumerate(self.members):
            assert (await self.send("开始修仙", member=index)).ok
            assert (await self.send("寻仙问道", member=index)).ok
            # Only progression and equipment are fixtures. All voyage materials
            # and the final commission inputs must come from actual combat.
            with self.runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator',realm_key='golden_core',realm_layer=1,"
                    "location_key='xuantian.floating_boat',stamina=100,stamina_max=100,energy=100,energy_max=100,"
                    "inventory_json='{}',spirit_stones=1000 WHERE platform=? AND platform_user_id=?", (adapter, user)
                )
            equip_damage_weapon(self.runtime, adapter, user, damage)
        await self.form(party_command=party_command, confirm=confirm)

    async def form(self, *, party_command="创建多人副本队伍", confirm=True):
        created = await self.send(party_command)
        assert created.code == "PARTY_CREATED", created.message
        self.party_id = created.data["party_id"]
        for index, (adapter, user) in enumerate(self.members[1:], 1):
            assert (await self.send(f"邀请入队 {adapter}:{user}")).ok
            assert (await self.send(f"接受入队 {self.party_id}", member=index)).ok
        if confirm:
            for index in range(len(self.members)):
                assert (await self.send(f"确认入队 {self.party_id}", member=index)).ok

    def players(self):
        with self.runtime.repository._connect() as connection:
            return tuple(dict(row) for row in connection.execute("SELECT * FROM players ORDER BY id"))

    async def start(self, operation):
        adapter, user = self.members[0]
        return await self.runtime.repository.start_party_battle(
            platform=adapter, platform_user_id=user, party_id=self.party_id, operation_id=operation,
        )

    async def restart(self):
        await self.runtime.close()
        self.runtime = create_runtime(data_dir=self.data, clock=self.clock)
        await self.runtime.repository.initialize()

    async def move(self, destination):
        started = await self.send(f"前往 {destination}")
        assert started.code == "TRAVEL_STARTED", started.message
        self.clock.advance(minutes=3)
        assert (await self.send("结算移动")).code == "TRAVEL_COMPLETED"


@pytest.mark.parametrize("adapter,size", [("qq.official", 4), ("onebot.v11", 5)])
def test_cloud_party_shared_public_combat_preview_replay_and_real_commission(tmp_path, adapter, size):
    async def run():
        team = Team(_copy_content(tmp_path), leader_adapter=adapter, size=size)
        try:
            await team.prepare()
            before = _database_state(team.runtime)
            preview = await team.send("多人副本预览", writable=False)
            assert preview.code == "PARTY_BATTLE_PREVIEW" and preview.data["can_start"], preview.message
            assert preview.data["cost"] == {"stamina": 12, "energy": 3}
            assert preview.data["reward"] == REWARD
            assert preview.data["daily_limit"] == 3
            assert {"recipe.weapon.cloud_sword", "recipe.array.gathering_basic", "town_commission.tide_supplies"} <= {row["key"] for row in preview.data["consumers"]}
            assert "云铁" in preview.message and "候潮备材" in preview.message
            assert _database_state(team.runtime) == before
            denied = await team.send("开始队伍战斗", "nonleader", member=1)
            assert denied.code == "PARTY_BATTLE_PERMISSION_DENIED"
            assert _database_state(team.runtime) == before

            for index in range(2):
                result = await team.send("开始队伍战斗", f"public-{index}")
                assert result.code == "PARTY_BATTLE_SETTLED" and result.data["outcome"] == "won", result.message
                assert all(reward == REWARD for reward in result.data["rewards"].values())
                assert len(result.data["member_rewards"]) == size
                assert all(row["reward"] == REWARD for row in result.data["member_rewards"])
                assert "成员所得" in result.message and "服务端" not in result.message
                assert any(action.command == f"队伍战斗回放 {result.data['battle_id']}" for action in result.actions)
                before_replay = team.players()
                replay = await team.send("开始队伍战斗", f"public-{index}")
                assert replay.ok and replay.data["idempotent_replay"]
                assert team.players() == before_replay
                before_conflict = _database_state(team.runtime)
                conflict = await team.send(f"开始队伍战斗 {team.party_id}", f"public-{index}")
                assert conflict.code == "OPERATION_CONFLICT"
                assert _database_state(team.runtime) == before_conflict
            for row in team.players():
                assert (row["stamina"], row["energy"]) == (76, 94)
                inventory = json.loads(row["inventory_json"])
                assert inventory[IRON] == 2 and inventory[SAND] == 2
            replay = await team.send(f"队伍战斗回放 {result.data['battle_id']}", member=1, writable=False)
            assert replay.code == "PARTY_BATTLE_REPLAY" and replay.data["actions"]

            await team.move("云城")
            await team.move("青石镇")
            assert (await team.send("城镇委托")).ok
            accepted = await team.send("接取委托 候潮备材")
            assert accepted.ok, accepted.message
            delivered = await team.send("交付委托 候潮备材", "handover")
            assert delivered.ok, delivered.message
            leader = team.players()[0]
            inventory = json.loads(leader["inventory_json"])
            assert inventory.get(IRON, 0) == 0 and inventory[SAND] == 1
            before_replay = team.players()
            assert (await team.send("交付委托 候潮备材", "handover")).data["idempotent_replay"]
            assert team.players() == before_replay
            help_result = await team.send("修仙帮助 社交", writable=False)
            assert "多人副本预览" in help_result.message and "云舟渡口" in help_result.message
        finally:
            await team.runtime.close()
    asyncio.run(run())


def test_cloud_party_member_blockers_atomic_entry_retry_quota_and_day_boundary(tmp_path):
    async def run():
        team = Team(_copy_content(tmp_path))
        try:
            await team.prepare(confirm=False)
            before = _database_state(team.runtime)
            preview = await team.send("队伍战备", writable=False)
            assert not preview.data["can_start"]
            # Creating a party confirms its leader; invited members confirm later.
            assert "unconfirmed" not in preview.data["members"][0]["blockers"]
            assert all("unconfirmed" in member["blockers"] for member in preview.data["members"][1:])
            assert (await team.send("开始队伍战斗", "unconfirmed")).code == "PARTY_BATTLE_REQUIREMENT_MISSING"
            assert _database_state(team.runtime) == before
            for index in range(4):
                assert (await team.send(f"确认入队 {team.party_id}", member=index)).ok

            for field, value, blocker, expected in (
                ("stamina", 11, "stamina", "PARTY_BATTLE_RESOURCE_INSUFFICIENT"),
                ("energy", 2, "energy", "PARTY_BATTLE_RESOURCE_INSUFFICIENT"),
                ("location_key", "xuantian.cloud_city", "location", "PARTY_BATTLE_REQUIREMENT_MISSING"),
                ("realm_key", "foundation", "realm", "PARTY_BATTLE_REQUIREMENT_MISSING"),
                ("status", "suspended", "unavailable", "PARTY_BATTLE_REQUIREMENT_MISSING"),
            ):
                original = team.players()[-1][field]
                with team.runtime.repository._connect() as connection:
                    connection.execute(f"UPDATE players SET {field}=? WHERE id=4", (value,))
                before = _database_state(team.runtime)
                preview = await team.send("多人副本预览", writable=False)
                assert blocker in preview.data["members"][-1]["blockers"]
                assert (await team.send("开始队伍战斗", f"deny-{field}")).code == expected
                assert _database_state(team.runtime) == before
                with team.runtime.repository._connect() as connection:
                    connection.execute(f"UPDATE players SET {field}=? WHERE id=4", (original,))

            cultivating = await team.send("开始修炼", member=3)
            assert cultivating.code == "CULTIVATION_STARTED", cultivating.message
            before = _database_state(team.runtime)
            preview = await team.send("多人副本预览")
            assert "busy" in preview.data["members"][-1]["blockers"]
            assert (await team.send("开始队伍战斗", "member-cultivating")).code == "PARTY_BATTLE_BUSY"
            assert _database_state(team.runtime) == before
            assert (await team.send("取消修炼", member=3)).ok

            with team.runtime.repository._connect() as connection:
                connection.execute("CREATE TRIGGER fail_entry BEFORE INSERT ON operations WHEN NEW.operation_id='entry-retry' BEGIN SELECT RAISE(ABORT, 'forced entry failure'); END")
            before = _database_state(team.runtime)
            assert (await team.send("开始队伍战斗", "entry-retry")).code == "PERSISTENCE_ERROR"
            assert _database_state(team.runtime) == before
            with team.runtime.repository._connect() as connection:
                connection.execute("DROP TRIGGER fail_entry")
            assert (await team.send("开始队伍战斗", "entry-retry")).data["outcome"] == "won"
            for index in range(2):
                assert (await team.send("开始队伍战斗", f"quota-{index}")).data["outcome"] == "won"
            before = _database_state(team.runtime)
            preview = await team.send("多人副本预览")
            assert all(member["daily_used"] == 3 and "daily_limit" in member["blockers"] for member in preview.data["members"])
            assert (await team.send("开始队伍战斗", "fourth")).code == "PARTY_BATTLE_DAILY_LIMIT"
            assert _database_state(team.runtime) == before

            for index in reversed(range(4)):
                assert (await team.send("退出队伍", member=index)).ok
            await team.form()
            assert (await team.send("开始队伍战斗", "switch-party")).code == "PARTY_BATTLE_DAILY_LIMIT"
            await team.restart()
            assert (await team.send("开始队伍战斗", "restart-quota")).code == "PARTY_BATTLE_DAILY_LIMIT"
            team.clock.value = team.clock.value.replace(hour=23, minute=59, second=59)
            preview = await team.send("多人副本预览")
            assert "expired" in preview.data["blockers"]
            assert all(member["daily_used"] == 3 for member in preview.data["members"])
            before = _database_state(team.runtime)
            assert (await team.send("开始队伍战斗", "expired-party")).code == "PARTY_BATTLE_REQUIREMENT_MISSING"
            assert _database_state(team.runtime) == before
            team.clock.advance(seconds=1)
            await team.form()
            preview = await team.send("多人副本预览")
            assert all(member["daily_used"] == 0 for member in preview.data["members"])
            assert (await team.send("开始队伍战斗", "new-day")).data["outcome"] == "won"
        finally:
            await team.runtime.close()
    asyncio.run(run())


def test_cloud_party_concurrent_entry_frozen_restart_closure_and_settlement_rollback(tmp_path):
    async def run():
        team = Team(_copy_content(tmp_path))
        try:
            await team.prepare()
            starts = await asyncio.gather(team.start("concurrent"), team.start("concurrent"))
            assert starts[0].battle_id == starts[1].battle_id
            assert sum(start.already_completed for start in starts) == 1
            with pytest.raises(PartyBattleBusyError):
                await team.start("second-battle")
            adapter, user = team.members[0]
            with pytest.raises(OperationConflictError):
                await team.runtime.repository.start_party_battle(platform=adapter, platform_user_id=user, party_id=None, operation_id="concurrent")
            assert all((row["stamina"], row["energy"]) == (88, 97) for row in team.players())
            before = _database_state(team.runtime)
            assert not (await team.send("多人副本预览")).data["can_start"]
            assert (await team.send("退出队伍")).code == "PARTY_STATE_CONFLICT"
            assert _database_state(team.runtime) == before
            battle_id = starts[0].battle_id
            with team.runtime.repository._connect() as connection:
                original_snapshot = connection.execute("SELECT snapshot_json FROM party_battle_sessions WHERE battle_id=?", (battle_id,)).fetchone()[0]
            for section, field, value in (("resource_cost", "energy", True), ("reward", IRON, True), (None, "entry_daily_limit", 0)):
                snapshot = json.loads(original_snapshot)
                (snapshot[section] if section else snapshot)[field] = value
                with team.runtime.repository._connect() as connection:
                    connection.execute("UPDATE party_battle_sessions SET snapshot_json=? WHERE battle_id=?", (json.dumps(snapshot), battle_id))
                before = _database_state(team.runtime)
                failed = await team.send(f"结算队伍战斗 {battle_id}", f"corrupt-{field}", member=1)
                assert failed.code == "PERSISTENCE_ERROR"
                assert _database_state(team.runtime) == before
            snapshot = json.loads(original_snapshot)
            del snapshot["entry_daily_limit"]
            with team.runtime.repository._connect() as connection:
                connection.execute("UPDATE party_battle_sessions SET snapshot_json=? WHERE battle_id=?", (json.dumps(snapshot), battle_id))
            before = _database_state(team.runtime)
            failed = await team.send(f"结算队伍战斗 {battle_id}", "corrupt-entry-limit-missing", member=1)
            assert failed.code == "PERSISTENCE_ERROR"
            assert _database_state(team.runtime) == before
            with team.runtime.repository._connect() as connection:
                connection.execute("UPDATE party_battle_sessions SET snapshot_json=? WHERE battle_id=?", (original_snapshot, battle_id))
            path = team.data / "战斗/敌人.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            enemy = next(row for row in document["records"] if row["key"] == ENEMY)
            enemy["combat_profile"]["party_profile"]["reward"] = {"cultivation": 999}
            enemy["combat_profile"]["party_profile"]["entry"] = {"stamina": 99, "energy": 99, "daily_limit": 1}
            enemy["status"] = "locked"
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            await team.restart()
            replay_start = await team.start("concurrent")
            assert replay_start.already_completed
            battle_id = starts[0].battle_id
            # Resolve combat first; inject failure only into the reward transaction.
            for round_no in range(1, 21):
                turn = await team.runtime.repository.run_party_battle_turn(battle_id=battle_id, expected_round=round_no)
                if turn["status"] not in {"created", "running"}:
                    break
            with team.runtime.repository._connect() as connection:
                connection.execute("CREATE TRIGGER fail_rewards BEFORE INSERT ON party_battle_rewards WHEN NEW.player_id=4 BEGIN SELECT RAISE(ABORT, 'forced reward failure'); END")
            before = _database_state(team.runtime)
            failed = await team.send(f"结算队伍战斗 {battle_id}", "settle-retry", member=1)
            assert failed.code == "PERSISTENCE_ERROR"
            assert _database_state(team.runtime) == before
            with team.runtime.repository._connect() as connection:
                connection.execute("DROP TRIGGER fail_rewards")
            results = await asyncio.gather(*(team.send(f"结算队伍战斗 {battle_id}", f"recover-{index}", member=index) for index in range(4)))
            assert all(result.ok and result.data["outcome"] == "won" for result in results)
            assert all(reward == REWARD for reward in results[0].data["rewards"].values())
            for row in team.players():
                inventory = json.loads(row["inventory_json"])
                assert inventory[IRON] == 1 and inventory[SAND] == 1
                assert row["stamina"] == 88 and row["energy"] == 97
            with team.runtime.repository._connect() as connection:
                assert connection.execute("SELECT COUNT(*) FROM party_battle_rewards").fetchone()[0] == 4
                assert connection.execute("SELECT COUNT(*) FROM party_battle_members WHERE asset_lock_status='locked'").fetchone()[0] == 0
            assert (await team.send("开始队伍战斗", "closed-new")).code == "PARTY_BATTLE_REQUIREMENT_MISSING"
        finally:
            await team.runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("outcome", ["lost", "expired"])
def test_cloud_party_loss_timeout_keeps_entry_cost_and_quota_without_victory_loot(tmp_path, outcome):
    async def run():
        team = Team(_copy_content(tmp_path))
        try:
            await team.prepare(damage=0)
            started = await team.start(f"failure-{outcome}")
            if outcome == "expired":
                team.clock.advance(seconds=61)
            result = await team.send(f"结算队伍战斗 {started.battle_id}", "failure-settle", member=1)
            assert result.ok and result.data["outcome"] == outcome, result.message
            assert all(not reward for reward in result.data["rewards"].values())
            assert all(not member["reward"] for member in result.data["member_rewards"])
            assert "无" in result.message
            for row in team.players():
                assert row["stamina"] == 88 and row["energy"] == 97
                inventory = json.loads(row["inventory_json"])
                assert inventory.get(IRON, 0) == inventory.get(SAND, 0) == 0
            preview = await team.send("多人副本预览")
            assert all(member["daily_used"] == 1 for member in preview.data["members"])
        finally:
            await team.runtime.close()
    asyncio.run(run())


def test_cloud_party_pair_cannot_bypass_standard_entry(tmp_path):
    async def run():
        team = Team(_copy_content(tmp_path), size=2)
        try:
            await team.prepare(party_command="创建双人队伍")
            before = _database_state(team.runtime)
            preview = await team.send("多人副本预览")
            assert "party_type" in preview.data["blockers"] and "member_count" in preview.data["blockers"]
            assert (await team.send("开始队伍战斗", "pair-bypass")).code == "PARTY_BATTLE_REQUIREMENT_MISSING"
            assert _database_state(team.runtime) == before
        finally:
            await team.runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("change", [
    {"entry": {"stamina": True, "energy": 3, "daily_limit": 3}},
    {"entry": {"stamina": -1, "energy": 3, "daily_limit": 3}},
    {"entry": {"stamina": 12, "energy": 3, "daily_limit": 0}},
    {"entry": {"stamina": 12, "energy": 3, "daily_limit": 3, "extra": 1}},
    {"party_type": "exploration_pair"},
    {"reward": {"item.missing": 1}},
    {"reward": {IRON: 2}},
    {"reward": {IRON: True}},
    {"reward": {"item.ticket.cloud_boat_fragment": 1}},
    {"reward": {"unknown_currency": 1}},
])
def test_cloud_party_rejects_malformed_costs_rewards_and_missing_consumers(tmp_path, change):
    data = _copy_content(tmp_path)
    path = data / "战斗/敌人.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    enemy = next(row for row in document["records"] if row["key"] == ENEMY)
    enemy["combat_profile"]["party_profile"].update(change)
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContentError):
        validate_combat_content(ContentBundle.load(data))


@pytest.mark.parametrize("reference,assets", [("enemy.missing", [IRON]), ("enemy.wood_rat", [IRON]), (ENEMY, ["item.mat.wood"])])
def test_cloud_party_source_requires_the_real_open_producer_and_payable_assets(tmp_path, reference, assets):
    data = _copy_content(tmp_path)
    path = data / "来源/来源.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    source = next(row for row in document["records"] if row["key"] == "source.party.cloud_boat")
    source["channels"][0]["reference"] = reference
    source["asset_keys"] = assets
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContentError, match="party enemy"):
        validate_source_content(ContentBundle.load(data))


def test_cloud_party_preview_empty_location_no_party_and_sdk_text_fallback(tmp_path, monkeypatch):
    async def run():
        from nonebot_plugin_xiuxian_3.adapters.message import markdown

        class Bot:
            async def send(self, event, message, **kwargs):
                self.message = str(message)
                return {"id": "simulated-party-reply"}

        team = Team(_copy_content(tmp_path), size=1)
        try:
            assert (await team.send("开始修仙")).ok
            before = _database_state(team.runtime)
            unsupported = await team.send("多人副本预览", writable=False)
            assert unsupported.ok and not unsupported.data["supported"]
            assert "云舟渡口" in unsupported.message
            assert _database_state(team.runtime) == before
            with team.runtime.repository._connect() as connection:
                connection.execute("UPDATE players SET location_key='xuantian.floating_boat',realm_key='golden_core',realm_layer=1")
            before = _database_state(team.runtime)
            preview = await team.send("多人副本预览", writable=False)
            assert preview.ok and "no_party" in preview.data["blockers"]
            assert any(action.command == "创建多人副本队伍" for action in preview.actions)
            monkeypatch.setattr(markdown, "qq_markdown_segment", lambda *args, **kwargs: None)
            for capabilities in (("text",), ("text", "markdown", "keyboard")):
                bot = Bot()
                sent = await markdown.send_markdown_message(bot, object(), preview.message, capabilities=capabilities, actions=preview.actions)
                assert sent.sent_format == "text" and sent.degraded
                assert "创建多人副本队伍" in bot.message and "云铁" in bot.message
                assert "PERSISTENCE_ERROR" not in bot.message
            assert _database_state(team.runtime) == before
        finally:
            await team.runtime.close()
    asyncio.run(run())
