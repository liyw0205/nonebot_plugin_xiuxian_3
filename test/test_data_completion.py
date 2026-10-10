from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from combat_fixtures import BALANCED_QUALIFICATION, equip_damage_weapon
from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.adventures.rules import bounty_definitions
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp, settlement_result
from nonebot_plugin_xiuxian_3.xiuxian.items.rules import resolve_item
from nonebot_plugin_xiuxian_3.xiuxian.production.rules import recipe_definitions


class Flow:
    def __init__(self, tmp_path):
        self.root = tmp_path / "content"
        shutil.copytree(Path(__file__).parents[1] / "data", self.root)
        self.now = datetime(2026, 10, 10, tzinfo=timezone.utc)
        self.runtime = create_runtime(data_dir=self.root, clock=lambda: self.now, adapters=("onebot.v11",))
        self.sequence = 0

    async def send(self, command, operation=None, *, user="player", ok=True):
        self.sequence += 1
        result = await self.runtime.adapters.dispatch(
            "onebot.v11",
            CommandContext(adapter="onebot.v11", user_id=user, request_id=str(self.sequence),
                           operation_id=operation or f"{user}:{self.sequence}", can_write_assets=True),
            command,
        )
        if ok:
            assert result.ok, (command, result.code, result.message)
        return result

    async def enter(self, choice="体修", *, user="player"):
        for command in ("开始修仙", "寻仙问道", "领取引路嘉奖 第一次寻仙", "完成引导 阅读",
                        "前往近郊", "完成引导 采集", "完成引导 布阵", f"选择道途 {choice}"):
            await self.send(command, user=user)

    def player(self, user="player"):
        with self.runtime.repository._connect() as db:
            return dict(db.execute("SELECT * FROM players WHERE platform_user_id=?", (user,)).fetchone())

    def inventory(self, user="player"):
        return json.loads(self.player(user)["inventory_json"])

    def dump(self):
        with self.runtime.repository._connect() as db:
            return tuple(db.iterdump())

    def context(self, **values):
        # Short tests replace accumulated realm/location/capacity only, never item sources or progress.
        assert set(values) <= {"realm_key", "realm_layer", "location_key", "carry_capacity",
                               "void_power", "void_power_max", "max_hp", "initiative", "qualification_json"}
        with self.runtime.repository._connect() as db:
            db.execute(f"UPDATE players SET {', '.join(key + '=?' for key in values)} WHERE platform_user_id='player'",
                       tuple(values.values()))

    async def gather(self, *, user="player"):
        self.now += timedelta(days=1)
        await self.send("恢复状态", user=user)
        prefix = f"gather:{user}:{self.sequence}"
        operation = next(
            f"{prefix}:{index}" for index in range(10000)
            if battle_roll_bp(f"{prefix}:{index}:battle") >= 1000
            and settlement_result("explore.gather_outskirts", f"{prefix}:{index}", content=self.runtime.content).get("item.mat.wood", 0) >= 1
            and settlement_result("explore.gather_outskirts", f"{prefix}:{index}", content=self.runtime.content).get("item.ore.ironstone", 0) >= 1
        )
        started = await self.send("开始探索 近郊采集", operation, user=user)
        self.now += timedelta(seconds=31)
        settled = await self.send("结算探索", user=user)
        assert settled.code == "EXPLORATION_SETTLED"
        assert settled.data["result"]["item.mat.wood"] >= 1
        return started

    async def produce(self, name, *, operation=None):
        started = await self.send(f"开始生产 {name}", operation)
        assert started.code == "PRODUCTION_STARTED"
        self.now = datetime.fromisoformat(started.data["ends_at"]) + timedelta(seconds=1)
        completed = await self.send("领取生产")
        assert completed.code == "PRODUCTION_COMPLETED" and completed.data["success"] is True
        return started, completed

    def trigger(self, operation, *, drop=False):
        with self.runtime.repository._connect() as db:
            if drop:
                db.execute("DROP TRIGGER fail_m7_ledger")
            else:
                db.execute("CREATE TRIGGER fail_m7_ledger BEFORE INSERT ON operations "
                           f"WHEN NEW.operation_name='{operation}' "
                           "BEGIN SELECT RAISE(ABORT, 'forced ledger failure'); END")


def _edit(root, relative, key, **values):
    path = root / relative
    document = json.loads(path.read_text(encoding="utf-8"))
    next(row for row in document["records"] if row["key"] == key).update(values)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _reload(flow):
    flow.runtime.content = ContentBundle.load(flow.root)
    flow.runtime.repository.content = flow.runtime.content


@pytest.mark.parametrize("field,value", [
    ("inputs", {"item.missing": 1}), ("outputs", {"item.mat.wood": True}),
    ("failure_refunds", {"item.mat.wood": 999}), ("profession", []),
    ("required_subprofession", ["unknown"]), ("required_realm", "unknown"),
    ("min_realm_layer", 11), ("tool_key", "item.mat.wood"),
    ("duration_seconds", 0), ("daily_limit", True), ("aliases", ["疗伤丹"]),
])
def test_recipe_loader_rejects_bad_contracts(tmp_path, field, value):
    flow = Flow(tmp_path)
    _edit(flow.root, "生产/配方.json", "recipe.companion.sack_small", **{field: value})
    with pytest.raises(ContentError):
        recipe_definitions(ContentBundle.load(flow.root))


def test_gear_source_must_reference_recipe_output(tmp_path):
    flow = Flow(tmp_path)
    _edit(flow.root, "灵兽/灵兽.json", "beast.gear.sack_small", source_recipe_key="recipe.food.spirit_rice")
    with pytest.raises(ContentError, match="does not produce"):
        recipe_definitions(ContentBundle.load(flow.root))


@pytest.mark.parametrize("flags", [[], ["permit.cloud_mine", "permit.cloud_mine"], [True], [""]])
def test_permit_rejects_bad_flag_definitions(tmp_path, flags):
    flow = Flow(tmp_path)
    _edit(flow.root, "道具/凭证.json", "item.permit.cloud_mine", effects=[{"type": "grant_intro_flags", "flags": flags}])
    with pytest.raises(ContentError):
        resolve_item("item.permit.cloud_mine", ContentBundle.load(flow.root))


@pytest.mark.parametrize("access", [
    {"type": "inventory_item", "item_key": "item.missing", "quantity": 1},
    {"type": "subprofession", "value": "missing"},
])
def test_mining_bounty_rejects_missing_access_references(tmp_path, access):
    flow = Flow(tmp_path)
    _edit(flow.root, "任务/悬赏.json", "bounty.cloud_mine", access_any=[access])
    with pytest.raises(ContentError):
        bounty_definitions(ContentBundle.load(flow.root))


def test_permit_cost_daily_cap_and_registered_reuse_are_atomic(tmp_path):
    async def run():
        flow = Flow(tmp_path)
        try:
            await flow.enter()
            for _ in range(2):
                await flow.gather()
            before = flow.player()
            inventory = flow.inventory()
            started, _ = await flow.produce("矿区登记", operation="first-permit")
            after = flow.player()
            assert after["spirit_stones"] == before["spirit_stones"] - 20
            assert after["energy"] == before["energy"] - 2
            assert flow.inventory()["item.mat.wood"] == inventory["item.mat.wood"] - 1
            assert flow.inventory()["item.ore.ironstone"] == inventory["item.ore.ironstone"] - 1
            snapshot = flow.dump()
            assert (await flow.send("开始生产 矿区登记", ok=False)).code == "RECIPE_DAILY_CAP"
            assert flow.dump() == snapshot
            assert (await flow.send("开始生产 recipe.nonexistent", ok=False)).code == "RECIPE_NOT_FOUND"
            assert flow.dump() == snapshot
            # Carried permit alone grants access before it is registered; no tools or mining subclass exist.
            flow.context(realm_key="foundation", realm_layer=1, location_key="xuantian.cloud_mine")
            mining = next(f"permit-mine:{i}" for i in range(1000) if battle_roll_bp(f"permit-mine:{i}:battle") >= 3000)
            await flow.send("开始探索 云铁矿区采集", mining)
            flow.now += timedelta(minutes=11)
            await flow.send("结算探索")
            await flow.send("使用物品 矿区采集许可", "register")
            flow.now += timedelta(days=1)
            await flow.send("恢复状态")
            await flow.produce("矿区登记")
            snapshot = flow.dump()
            rejected = await flow.send("使用物品 矿区采集许可", "duplicate", ok=False)
            assert rejected.code == "ITEM_EFFECT_ALREADY_ACTIVE" and "已登记" in rejected.message
            assert flow.dump() == snapshot and flow.inventory()["item.permit.cloud_mine"] == 1
            assert started.data["recipe_key"] == "recipe.permit.cloud_mine"
        finally:
            await flow.runtime.close()
    asyncio.run(run())


def test_public_mining_permit_tools_bounty_and_gear_consumption(tmp_path):
    async def run():
        flow = Flow(tmp_path)
        try:
            await flow.enter()
            for _ in range(7):
                await flow.gather()
            await flow.send("返回新手城")
            await flow.send("开始主线 1")
            await flow.send("领取主线奖励 1")
            mount = await flow.send("结缘灵骑 竹鹿")
            await flow.send("前往近郊")
            beast = await flow.send("结缘灵兽 木鼠")
            await flow.produce("矿区登记", operation="permit-start")
            before = flow.dump()
            flow.trigger("items.use")
            assert (await flow.send("使用物品 矿区采集许可", "permit-use", ok=False)).code == "PERSISTENCE_ERROR"
            flow.trigger("items.use", drop=True)
            assert flow.dump() == before
            used = await flow.send("使用物品 矿区采集许可", "permit-use")
            assert set(used.data["effect"]["flags"]) == {"permit.cloud_mine", "cloud_mine.permit", "commission.cloud_mine"}
            assert flow.inventory().get("item.permit.cloud_mine", 0) == 0
            before = flow.dump()
            replay = await flow.send("使用物品 矿区采集许可", "permit-use")
            assert replay.data["idempotent_replay"] is True and flow.dump() == before
            with flow.runtime.repository._connect() as db:
                receipt = db.execute("SELECT result_json FROM operations WHERE operation_id='permit-use'").fetchone()[0]
                damaged = json.loads(receipt)
                damaged["effect"]["flags"] = ["unearned.access"]
                db.execute("UPDATE operations SET result_json=? WHERE operation_id='permit-use'", (json.dumps(damaged),))
            before = flow.dump()
            assert (await flow.send("使用物品 矿区采集许可", "permit-use", ok=False)).code == "PERSISTENCE_ERROR"
            assert flow.dump() == before
            with flow.runtime.repository._connect() as db:
                db.execute("UPDATE operations SET result_json=? WHERE operation_id='permit-use'", (receipt,))
            assert (await flow.send("使用物品 矿区采集许可", "permit-use")).data["idempotent_replay"] is True
            await flow.produce("基础矿镐")
            assert flow.inventory()["item.tool.mining_pickaxe"] == 1
            before = flow.dump()
            assert (await flow.send("开始生产 精制矿镐", ok=False)).code == "RECIPE_REQUIREMENT_MISSING"
            assert flow.dump() == before
            flow.context(realm_key="qi_gathering", realm_layer=1)
            await flow.produce("精制矿镐")
            assert flow.inventory().get("item.tool.mining_pickaxe", 0) == 0
            assert flow.inventory()["item.tool.mining_pickaxe_t2"] == 1
            await flow.produce("小型灵兽行囊")
            await flow.produce("竹鹿鞍具")
            await flow.enter(user="seller")
            for _ in range(2):
                await flow.gather(user="seller")
            await flow.send("返回新手城", user="seller")
            await flow.send("返回新手城")
            sale = await flow.send("发布摆摊 木材 1 1", user="seller")
            flow.context(carry_capacity=sum(flow.inventory().values()))
            buy = f"购买摆摊 {sale.data['order_id']} 1"
            before = flow.dump()
            denied = await flow.send(buy, "sack-buy", ok=False)
            assert denied.code == "MARKET_BUYER_CAPACITY_INSUFFICIENT"
            assert flow.dump() == before
            before_stats = (await flow.send("我的属性")).data
            gear_command = f"装备灵具 {beast.data['instance_id']} 小型灵兽行囊"
            before = flow.dump()
            flow.trigger("companion.equip_gear")
            failed = await flow.send(gear_command, "sack-equip", ok=False)
            assert failed.code == "PERSISTENCE_ERROR"
            flow.trigger("companion.equip_gear", drop=True)
            assert flow.dump() == before
            await flow.send(gear_command, "sack-equip")
            assert flow.inventory().get("beast.gear.sack_small", 0) == 0
            after_stats = (await flow.send("我的属性")).data
            assert after_stats["derived_stats"]["carry_capacity"] == before_stats["derived_stats"]["carry_capacity"] + 5
            frozen = await flow.runtime.repository.freeze_stats(platform="onebot.v11", platform_user_id="player",
                                                               operation_id="sack-stats", purpose="exploration")
            assert any(ref.get("key") == "companion_gear" for ref in frozen.source_refs)
            before = flow.dump()
            assert (await flow.send(gear_command, "sack-equip")).data["idempotent_replay"] is True
            assert flow.dump() == before
            with flow.runtime.repository._connect() as db:
                assert db.execute("SELECT COUNT(*) FROM companion_gear_instances WHERE gear_key='beast.gear.sack_small'").fetchone()[0] == 1
            assert (await flow.send(buy, "sack-buy")).code == "MARKET_ORDER_PURCHASED"
            order = await flow.send("发布求购 木材 1 1")
            await flow.send(f"匹配求购 {order.data['order_id']}", user="seller")
            assert (await flow.send(f"交付求购 {order.data['order_id']}", user="seller")).code == "PURCHASE_ORDER_SETTLED"
            await flow.send(f"装备灵具 {mount.data['instance_id']} 竹鹿鞍具")
            await flow.send("返回新手城")
            preview = await flow.send(f"运输预览 止血草 1 {mount.data['instance_id']}")
            assert preview.data["mount_stamina_cost"] == 1
            transport = await flow.send(f"开始运输 止血草 1 {mount.data['instance_id']}", "saddle-route")
            self_route = transport.data["route_id"]
            flow.now += timedelta(hours=1)
            assert (await flow.send(f"结算运输 {self_route}", "saddle-settle")).code == "ROUTE_SETTLED"
            before = flow.dump()
            assert (await flow.send(f"结算运输 {self_route}", "saddle-settle")).data["idempotent_replay"] is True
            assert flow.dump() == before

            # Replace only accumulated realm; the permit, tools, mine items and bounty remain public.
            flow.context(realm_key="foundation", realm_layer=4)
            flow.now += timedelta(days=1)
            await flow.send("恢复状态")
            await flow.send("返回新手城")
            await flow.send("前往 云铁矿区")
            flow.now += timedelta(minutes=3)
            await flow.send("结算移动")
            accepted = await flow.send("接取悬赏 云铁矿区悬赏", "mine-bounty")
            assert accepted.code == "BOUNTY_ACCEPTED"
            assert (await flow.send("领取悬赏", ok=False)).code == "BOUNTY_NOT_COMPLETE"
            for index in range(3):
                if index == 2:
                    flow.now += timedelta(minutes=40)
                    await flow.send("恢复状态")
                operation = next(f"mine:{index}:{i}" for i in range(1000) if battle_roll_bp(f"mine:{index}:{i}:battle") >= 3000)
                await flow.send("开始探索 云铁矿区采集", operation)
                flow.now += timedelta(minutes=11)
                await flow.send("结算探索")
            before = flow.inventory()
            claimed = await flow.send("领取悬赏", "mine-claim")
            assert claimed.code == "BOUNTY_CLAIMED"
            assert claimed.data["rewards"]
            assert flow.inventory()["item.material.cloud_iron"] == before["item.material.cloud_iron"]
            snapshot = flow.dump()
            assert (await flow.send("领取悬赏", "mine-claim")).data["idempotent_replay"] is True
            assert flow.dump() == snapshot
        finally:
            await flow.runtime.close()
    asyncio.run(run())


def test_public_cooking_and_mining_entry_rewards(tmp_path):
    async def run():
        flow = Flow(tmp_path)
        try:
            await flow.enter("辅修 采矿", user="miner")
            assert flow.player("miner")["subprofession_key"] == "mining"
            assert flow.inventory("miner")["item.tool.mining_pickaxe"] == 1
            await flow.enter("辅修 烹饪")
            assert flow.player()["subprofession_key"] == "cooking"
            assert flow.inventory()["item.food.coarse_spirit_rice"] >= 2
            _, cooked = await flow.produce("灵米饭")
            assert cooked.data["outputs"] == {"item.food.spirit_rice": 2}
            used = await flow.send("使用物品 灵米饭 精力", "rice-use")
            assert used.data["effect"]["resource"] == "energy" and used.data["effect"]["restored"] >= 1
            before = flow.dump()
            assert (await flow.send("使用物品 灵米饭 精力", "rice-use")).data["idempotent_replay"] is True
            assert flow.dump() == before
            await flow.send("返回新手城")
            await flow.send("开始主线 1")
            await flow.send("领取主线奖励 1")
            await flow.send("开始主线 2")
            await flow.send("领取主线奖励 2")
            flow.context(realm_key="qi_gathering", realm_layer=1, location_key="xuantian.spirit_field")
            _, tea = await flow.produce("云灵茶")
            assert tea.data["outputs"] == {"item.food.cloud_tea": 3}
            used = await flow.send("使用物品 云灵茶")
            assert used.data["effect"]["pending"] is True
        finally:
            await flow.runtime.close()
    asyncio.run(run())


def test_recipe_json_changes_new_orders_but_not_old_replay_and_recovery(tmp_path):
    async def run():
        flow = Flow(tmp_path)
        try:
            await flow.enter()
            for _ in range(2):
                await flow.gather()
            before = flow.dump()
            flow.trigger("production.start")
            assert (await flow.send("开始生产 recipe.companion.sack_small", "start", ok=False)).code == "PERSISTENCE_ERROR"
            flow.trigger("production.start", drop=True)
            assert flow.dump() == before
            started = await flow.send("开始生产 recipe.companion.sack_small", "start")
            _edit(flow.root, "生产/配方.json", "recipe.companion.sack_small", status="locked", currency_cost=999)
            _reload(flow)
            before = flow.dump()
            assert (await flow.send("开始生产 recipe.companion.sack_small", "start")).data["idempotent_replay"] is True
            assert flow.dump() == before
            assert (await flow.send("开始生产 recipe.companion.sack_small", "new", ok=False)).code == "RECIPE_NOT_FOUND"
            flow.now = datetime.fromisoformat(started.data["ends_at"]) + timedelta(seconds=1)
            before = flow.dump()
            flow.trigger("production.complete")
            assert (await flow.send("领取生产", "complete", ok=False)).code == "PERSISTENCE_ERROR"
            flow.trigger("production.complete", drop=True)
            assert flow.dump() == before
            completed = await flow.send("领取生产", "complete")
            assert completed.data["outputs"] == {"beast.gear.sack_small": 1}
            before = flow.dump()
            assert (await flow.send("领取生产", "complete")).data["idempotent_replay"] is True
            assert flow.dump() == before
            _edit(flow.root, "生产/配方.json", "recipe.companion.sack_small", status="active", currency_cost=1,
                  success_threshold_bp=10000, high_quality_threshold_bp=10001)
            _reload(flow)
            for _ in range(2):
                await flow.gather()
            preview = await flow.send("生产预览 小型灵兽行囊")
            assert preview.data["currency_cost"] == 1
            failing = await flow.send("开始生产 小型灵兽行囊", "failing")
            flow.now = datetime.fromisoformat(failing.data["ends_at"]) + timedelta(seconds=1)
            failed = await flow.send("领取生产")
            assert failed.data["success"] is False
            assert failed.data["refunds"] == {"item.mat.wood": 1}
            await flow.gather()
            expired = await flow.send("开始生产 小型灵兽行囊", "expiring")
            flow.now = datetime.fromisoformat(expired.data["ends_at"]) + timedelta(hours=25)
            assert (await flow.send("领取生产", ok=False)).code == "ORDER_EXPIRED"
            await flow.runtime.close()
            flow.runtime = create_runtime(data_dir=flow.root, clock=lambda: flow.now, adapters=("onebot.v11",))
            recovered = await flow.send("恢复生产", "recover")
            assert recovered.code == "PRODUCTION_RECOVERED"
            before = flow.dump()
            assert (await flow.send("恢复生产", "recover")).data["idempotent_replay"] is True
            assert flow.dump() == before
            _edit(flow.root, "生产/配方.json", "recipe.companion.sack_small", inputs={"item.missing": 1})
            _reload(flow)
            before = flow.dump()
            assert (await flow.send("开始生产 小型灵兽行囊", ok=False)).code == "PERSISTENCE_ERROR"
            assert flow.dump() == before
        finally:
            await flow.runtime.close()
    asyncio.run(run())


def test_public_void_trial_production_and_energy_crystal_consumption(tmp_path):
    async def run():
        flow = Flow(tmp_path)
        try:
            await flow.enter()
            # Only growth/combat ability is a fixture; all virtual-node materials are server rewards.
            flow.context(realm_key="soul_transformation", realm_layer=1, location_key="void.portal",
                         max_hp=10000, initiative=100, qualification_json=json.dumps(BALANCED_QUALIFICATION))
            equip_damage_weapon(flow.runtime, "onebot.v11", "player", 5000)
            for _ in range(2):
                trial = await flow.send("开始界壁试炼")
                assert trial.data["outcome"] == "won"
            assert flow.inventory()["item.void_crystal"] == 4 and flow.inventory()["item.void_anchor"] == 4
            flow.context(realm_key="void_refining", realm_layer=1, void_power=80, void_power_max=100)
            _, completed = await flow.produce("虚空晶炼制")
            assert completed.data["outputs"] == {"item.void_power_crystal": 2}
            used = await flow.send("使用物品 虚空能量晶 虚力", "void-use")
            assert used.data["effect"]["requested"] == 40 and used.data["effect"]["restored"] == 20
            assert flow.player()["void_power"] == 100
            before = flow.dump()
            assert (await flow.send("使用物品 虚空能量晶 虚力", "void-use")).data["idempotent_replay"] is True
            assert flow.dump() == before
            assert (await flow.send("使用物品 虚空能量晶 虚力", ok=False)).code == "ITEM_COOLDOWN"
            assert flow.dump() == before
            flow.now += timedelta(seconds=301)
            flow.context(void_power=0, void_power_max=0)
            before = flow.dump()
            assert (await flow.send("使用物品 虚空能量晶 虚力", ok=False)).code == "ITEM_NOT_USABLE"
            assert flow.dump() == before
        finally:
            await flow.runtime.close()
    asyncio.run(run())


def test_sack_explanation_and_durability_follow_frozen_attribute_source(tmp_path):
    async def run():
        flow = Flow(tmp_path)
        try:
            await flow.enter()
            for _ in range(2):
                await flow.gather()
            await flow.produce("小型灵兽行囊")
            beast = await flow.send("结缘灵兽 木鼠")
            before = (await flow.send("我的属性")).data["derived_stats"]["carry_capacity"]
            await flow.send(f"装备灵具 {beast.data['instance_id']} 小型灵兽行囊")
            explanation = await flow.send("属性说明 负重")
            assert "灵兽行囊" in explanation.message and "companion_gear" not in explanation.message
            assert explanation.data["value"] == before + 5
            frozen = await flow.runtime.repository.freeze_stats(platform="onebot.v11", platform_user_id="player",
                                                               operation_id="carry-frozen", purpose="exploration")
            # Simulate wear only; the equipped gear itself came from the public recipe above.
            with flow.runtime.repository._connect() as db:
                db.execute("UPDATE companion_gear_instances SET durability_bp=0 WHERE gear_key='beast.gear.sack_small'")
            assert (await flow.send("我的属性")).data["derived_stats"]["carry_capacity"] == before
            replay = await flow.runtime.repository.freeze_stats(platform="onebot.v11", platform_user_id="player",
                                                               operation_id="carry-frozen", purpose="exploration")
            assert replay.already_completed and replay.payload() == frozen.payload()
        finally:
            await flow.runtime.close()
    asyncio.run(run())
