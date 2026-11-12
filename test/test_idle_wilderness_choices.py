from __future__ import annotations

import asyncio
import json
import sqlite3
from urllib.parse import unquote

import pytest

from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentError
from nonebot_plugin_xiuxian_3.xiuxian.production.rules import recipe_definitions, random_quality_bp
from nonebot_plugin_xiuxian_3.xiuxian.specials.idle_rules import idle_route_definitions, select_wilderness_choice
from test.test_wilderness_idle import Clock, send, starter, move, state
from test.test_wilderness_idle import change_content


def test_six_choices_have_distinct_costs_rewards_and_consumers():
    routes = [r for r in idle_route_definitions().values() if r.wilderness_event]
    assert len(routes) == 3
    for route in routes:
        choices = [select_wilderness_choice(route, c['name']) for c in route.wilderness_event['choices']]
        assert len(choices) == 2
        assert choices[0].pool_key != choices[1].pool_key
        assert choices[0].gathering_journal != choices[1].gathering_journal
        assert all(c.gathering_journal['uses'] for c in choices)


@pytest.mark.parametrize('damage', [
    'scene', 'single_choice', 'duplicate', 'boolean_cost', 'pool',
    'blank_text', 'recipe', 'consumer', 'weight',
])
def test_event_choice_content_rejects_invalid_fields_and_references(damage):
    def mutate(records):
        event = records['livelihood', 'idle.herb_vale_gather']['wilderness_event']
        choice = event['choices'][0]
        if damage == 'scene':
            event['scene'] = ' '
        elif damage == 'single_choice':
            event['choices'].pop()
        elif damage == 'duplicate':
            event['choices'][1]['name'] = choice['name']
        elif damage == 'boolean_cost':
            choice['cost']['stamina'] = True
        elif damage == 'pool':
            choice['reward_pool_key'] = 'reward_pool.missing'
        elif damage == 'blank_text':
            choice['complete_text'] = ' '
        elif damage == 'recipe':
            choice['recipe_keys'] = ['recipe.missing']
        elif damage == 'consumer':
            choice['recipe_keys'] = ['recipe.array.gathering_basic']
        else:
            records['reward', choice['reward_pool_key']]['outcomes'][0]['weight'] = 0
    with pytest.raises(ContentError):
        idle_route_definitions(change_content(mutate))


def player(runtime):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.row_factory = sqlite3.Row
        return dict(connection.execute(
            "SELECT * FROM players WHERE platform='onebot.v11' AND platform_user_id='gatherer'"
        ).fetchone())


@pytest.mark.parametrize('choice', ['扶徒归棚', '辨叶上坡'])
def test_public_choice_restart_cost_reward_replay_and_cancel(tmp_path, choice):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await starter(runtime)
            await move(runtime, clock, '百草坡')
            preview = await send(runtime, '挂机预览 百草坡采药')
            assert choice in preview.message
            before = state(runtime)
            denied = await send(runtime, '开始挂机 百草坡采药 不存在', 'bad')
            assert denied.code == 'IDLE_REQUIREMENT_MISSING'
            assert denied.data['reason'] and denied.data['subject']
            assert state(runtime) == before
            original = player(runtime)
            started = await send(runtime, f'开始挂机 百草坡采药 {choice}', 'start')
            assert started.ok, started.message
            assert choice in started.message
            selected = select_wilderness_choice(idle_route_definitions()['idle.herb_vale_gather'], choice)
            changed = player(runtime)
            assert original['stamina'] - changed['stamina'] == selected.stamina_cost
            assert original['energy'] - changed['energy'] == selected.energy_cost
            before = state(runtime)
            assert (await send(runtime, f'开始挂机 百草坡采药 {choice}', 'start')).data['idempotent_replay']
            assert state(runtime) == before
            conflict = await send(runtime, '开始挂机 百草坡采药', 'start')
            assert conflict.code == 'OPERATION_CONFLICT' and state(runtime) == before
            with sqlite3.connect(runtime.settings.database_path) as connection:
                frozen = json.loads(connection.execute('SELECT snapshot_json FROM idle_assignments').fetchone()[0])
            await runtime.close()
            clock.advance(hours=4)
            runtime = create_runtime(data_dir=tmp_path, clock=clock)
            status = await send(runtime, '挂机状态')
            assert choice in status.message and status.data['claimable']
            claimed = await send(runtime, '领取挂机', 'claim')
            assert claimed.ok, claimed.message
            assert claimed.data['reward'] == frozen['full_reward']
            assert frozen['gathering_journal']['complete_text'] in claimed.message
            before = state(runtime)
            assert (await send(runtime, '领取挂机', 'claim')).data['idempotent_replay']
            assert state(runtime) == before
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize('fault', ['reward', 'ledger', 'journal'])
def test_choice_rollback_retry_closed_content_and_huge_balances(tmp_path, monkeypatch, fault):
    async def run():
        from nonebot_plugin_xiuxian_3.xiuxian.specials import idle_repository
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await starter(runtime)
            await move(runtime, clock, '百草坡')
            huge = 10 ** 100
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute('UPDATE players SET spirit_stones=?,total_cultivation=?', (str(huge).encode(), str(huge).encode()))
            started = await send(runtime, '开始挂机 百草坡采药 扶徒归棚', 'start')
            assert started.ok, started.message
            with sqlite3.connect(runtime.settings.database_path) as connection:
                frozen = json.loads(connection.execute('SELECT snapshot_json FROM idle_assignments').fetchone()[0])
            clock.advance(hours=4)
            def close(records):
                records['livelihood', 'idle.herb_vale_gather']['status'] = 'locked'
                records['reward', 'reward_pool.idle.event.herb_shelter']['status'] = 'locked'
            runtime.repository.content = change_content(close)
            original_grant = idle_repository.grant_player_reward
            original_ledger = runtime.repository._record_idle_operation
            if fault == 'reward':
                def fail(*args, **kwargs):
                    original_grant(*args, **kwargs)
                    raise RuntimeError('injected event reward failure')
                monkeypatch.setattr(idle_repository, 'grant_player_reward', fail)
            elif fault == 'ledger':
                def fail(*args, **kwargs):
                    raise RuntimeError('injected event ledger failure')
                monkeypatch.setattr(runtime.repository, '_record_idle_operation', fail)
            else:
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    bad = {**frozen, 'gathering_journal': {'uses': 'bad'}}
                    connection.execute('UPDATE idle_assignments SET snapshot_json=?', (json.dumps(bad),))
            before = state(runtime)
            with pytest.raises((ValueError, RuntimeError), match='injected|gathering_journal'):
                await send(runtime, '领取挂机', 'claim')
            assert state(runtime) == before
            monkeypatch.setattr(idle_repository, 'grant_player_reward', original_grant)
            monkeypatch.setattr(runtime.repository, '_record_idle_operation', original_ledger)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute('UPDATE idle_assignments SET snapshot_json=?', (json.dumps(frozen),))
            claimed = await send(runtime, '领取挂机', 'claim')
            assert claimed.ok and claimed.data['reward'] == frozen['full_reward']
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stones, cultivation = connection.execute('SELECT spirit_stones,total_cultivation FROM players').fetchone()
                assert int(stones) == huge and int(cultivation) == huge
        finally:
            await runtime.close()
    asyncio.run(run())


def test_choice_cancel_refunds_extra_cost_and_concurrent_claim_is_once(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        other = None
        try:
            await starter(runtime)
            await move(runtime, clock, '百草坡')
            assert (await send(runtime, '开始挂机 百草坡采药 扶徒归棚', 'start-cancel')).ok
            cancelled = await send(runtime, '取消挂机', 'cancel')
            assert cancelled.data['refunded'] == {'stamina': 3, 'energy': 1}
            assert (await send(runtime, '开始挂机 百草坡采药 辨叶上坡', 'start')).ok
            clock.advance(hours=4)
            other = create_runtime(data_dir=tmp_path, clock=clock)
            await other.repository.initialize()
            inventory = json.loads(player(runtime)['inventory_json'])
            claims = await asyncio.gather(send(runtime, '领取挂机', 'claim-a'), send(other, '领取挂机', 'claim-b'))
            assert sum(c.ok for c in claims) == 1
            assert {c.code for c in claims} <= {'IDLE_CLAIMED', 'IDLE_NOT_FOUND', 'IDLE_ALREADY_SETTLED'}
            award = next(result for result in claims if result.ok).data['reward']
            after = json.loads(player(runtime)['inventory_json'])
            assert all(after.get(key, 0) - inventory.get(key, 0) == count for key, count in award.items() if key.startswith('item.'))
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM operations WHERE operation_name='specials.claim_idle'").fetchone()[0] == 1
        finally:
            if other is not None:
                await other.close()
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize('choice', ['顺纹取材', '翻根寻铁'])
def test_ironwood_event_public_materials_feed_actual_pickaxe_production(tmp_path, choice):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await starter(runtime)
            await move(runtime, clock, '铁木林')
            assert (await send(runtime, f'开始挂机 铁木林拾材 {choice}', 'start')).ok
            clock.advance(hours=6)
            claimed = await send(runtime, '领取挂机', 'claim')
            assert claimed.ok, claimed.message
            if claimed.data['reward']['item.ore.ironstone'] < 2:
                clock.advance(days=1)
                assert (await send(runtime, '开始挂机 铁木林拾材 翻根寻铁', 'start-next')).ok
                clock.advance(hours=6)
                assert (await send(runtime, '领取挂机', 'claim-next')).ok
            # Existing resource recovery, no injected materials or source ledger.
            assert (await send(runtime, '返回新手城')).ok
            assert (await send(runtime, '租住居所 客房')).ok
            assert (await send(runtime, '休整')).ok
            clock.advance(minutes=30)
            assert (await send(runtime, '结算休整')).ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                before = json.loads(connection.execute('SELECT inventory_json FROM players').fetchone()[0])
            produced = await send(runtime, '开始生产 基础矿镐', 'produce')
            assert produced.ok, produced.message
            with sqlite3.connect(runtime.settings.database_path) as connection:
                after = json.loads(connection.execute('SELECT inventory_json FROM players').fetchone()[0])
            assert after.get('item.mat.wood', 0) == before['item.mat.wood'] - 1
            assert after.get('item.ore.ironstone', 0) == before['item.ore.ironstone'] - 2
            clock.advance(seconds=30)
            result = await send(runtime, '领取生产', 'produce-claim')
            assert result.ok, result.message
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize('choice,recipe_name', [
    ('扶徒归棚', '低阶疗伤丹'), ('辨叶上坡', '焦点丹'),
])
def test_herb_event_public_materials_are_consumed_by_pill_recipes(tmp_path, choice, recipe_name):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await starter(runtime, path='辅修 炼丹')
            await move(runtime, clock, '百草坡')
            generated = {}
            for day in range(2):
                if day:
                    clock.advance(days=1)
                started = await send(runtime, f'开始挂机 百草坡采药 {choice}', f'herb-{day}')
                assert started.ok, started.message
                clock.advance(hours=4)
                claimed = await send(runtime, '领取挂机', f'herb-claim-{day}')
                assert claimed.ok, claimed.message
                for key, amount in claimed.data['reward'].items():
                    generated[key] = generated.get(key, 0) + amount
                if choice == '扶徒归棚' or generated.get('item.herb.spirit_leaf', 0) >= 2:
                    break
            assert generated['item.herb.blood_grass'] >= (2 if choice == '扶徒归棚' else 1)
            if choice == '辨叶上坡':
                assert generated['item.herb.spirit_leaf'] >= 2
                assert not generated.get('local.xuantian.new_town')
            else:
                assert generated['local.xuantian.new_town'] == 1
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    local = json.loads(connection.execute('SELECT local_json FROM player_reputations').fetchone()[0])
                    assert local['local.xuantian.new_town'] >= 1
            before = player(runtime)
            inventory = json.loads(before['inventory_json'])
            assert inventory['item.tool.basic_furnace'] >= 1
            recipe = next(r for r in recipe_definitions().values() if r.name == recipe_name)
            operation = next(f'herb-production-{i}' for i in range(100) if random_quality_bp(f'herb-production-{i}') == 1000)
            production = await send(runtime, '开始生产 ' + recipe_name, operation)
            assert production.ok, production.message
            after = json.loads(player(runtime)['inventory_json'])
            assert all(inventory.get(key, 0) - after.get(key, 0) == cost for key, cost in recipe.inputs.items())
            clock.advance(seconds=recipe.duration_seconds)
            completed = await send(runtime, '领取生产', 'herb-production-claim')
            assert completed.ok and completed.data['success'], completed.message
            final = json.loads(player(runtime)['inventory_json'])
            assert all(final.get(key, 0) - after.get(key, 0) == amount for key, amount in completed.data['outputs'].items())
        finally:
            await runtime.close()
    asyncio.run(run())


def test_event_start_and_cancel_across_runtimes_are_atomic(tmp_path, monkeypatch):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        other = None
        try:
            await starter(runtime)
            await move(runtime, clock, '百草坡')
            original = player(runtime)
            other = create_runtime(data_dir=tmp_path, clock=clock)
            await other.repository.initialize()
            starts = await asyncio.gather(
                send(runtime, '开始挂机 百草坡采药 扶徒归棚', 'race-shelter'),
                send(other, '开始挂机 百草坡采药 辨叶上坡', 'race-ridge'),
            )
            assert sum(result.ok for result in starts) == 1
            assert {result.code for result in starts} == {'IDLE_STARTED', 'IDLE_BUSY'}
            assert next(result for result in starts if not result.ok).data['reason']
            with sqlite3.connect(runtime.settings.database_path) as connection:
                cost = json.loads(connection.execute('SELECT cost_json FROM idle_assignments').fetchone()[0])
            changed = player(runtime)
            assert original['stamina'] - changed['stamina'] == cost['stamina']
            assert original['energy'] - changed['energy'] == cost['energy']
            cancels = await asyncio.gather(send(runtime, '取消挂机', 'race-cancel-a'), send(other, '取消挂机', 'race-cancel-b'))
            assert sum(result.ok for result in cancels) == 1
            assert {result.code for result in cancels} == {'IDLE_CANCELLED', 'IDLE_NOT_FOUND'}
            winner = next(result for result in cancels if result.ok)
            assert winner.data['refunded'] == cost
            restored = player(runtime)
            assert restored['stamina'] == original['stamina'] and restored['energy'] == original['energy']
            before = state(runtime)
            assert (await send(runtime, '取消挂机', winner.operation_id)).data['idempotent_replay']
            assert state(runtime) == before
            record = runtime.repository._record_idle_operation
            def fail(*args, **kwargs):
                record(*args, **kwargs)
                raise RuntimeError('injected event start receipt failure')
            monkeypatch.setattr(runtime.repository, '_record_idle_operation', fail)
            with pytest.raises(RuntimeError, match='start receipt'):
                await send(runtime, '开始挂机 百草坡采药 扶徒归棚', 'fault-start')
            assert state(runtime) == before
            monkeypatch.setattr(runtime.repository, '_record_idle_operation', record)
            assert (await send(runtime, '开始挂机 百草坡采药 扶徒归棚', 'fault-start')).ok
            clock.advance(seconds=61)
            before = state(runtime)
            expired = await send(runtime, '取消挂机', 'expired-cancel')
            assert expired.code == 'IDLE_CANCEL_WINDOW_EXPIRED'
            assert expired.data['reason'] == 'idle cancellation window expired'
            assert expired.data['subject'] == '本人闲居安排' and state(runtime) == before
        finally:
            if other is not None:
                await other.close()
            await runtime.close()
    asyncio.run(run())


def test_basalt_choice_sand_flows_through_public_array_recipe(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await starter(runtime, path='辅修 布阵')
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE players SET realm_key='qi_gathering',realm_layer=1 WHERE platform_user_id='gatherer'")
            await move(runtime, clock, '玄武岩径')
            preview = await send(runtime, '挂机预览 玄武岩径筛砂')
            assert '复筛细砂' in preview.message and '循缝拾铁' in preview.message
            assert '基础聚灵阵' in preview.message
            started = await send(runtime, '开始挂机 玄武岩径筛砂 复筛细砂', 'start')
            assert started.ok, started.message
            clock.advance(hours=8)
            claimed = await send(runtime, '领取挂机', 'claim')
            assert claimed.ok, claimed.message
            inventory = json.loads(sqlite3.connect(runtime.settings.database_path).execute("SELECT inventory_json FROM players").fetchone()[0])
            assert inventory['item.mat.array_sand'] >= 3
            await move(runtime, clock, '近郊')
            await move(runtime, clock, '青石镇')
            await move(runtime, clock, '灵泉谷')
            produced = await send(runtime, '开始生产 基础聚灵阵', 'array')
            assert produced.ok, produced.message
            after = json.loads(sqlite3.connect(runtime.settings.database_path).execute("SELECT inventory_json FROM players").fetchone()[0])
            assert after['item.mat.array_sand'] == inventory['item.mat.array_sand'] - 2
            clock.advance(seconds=90)
            assert (await send(runtime, '领取生产', 'array-claim')).ok
            final = json.loads(sqlite3.connect(runtime.settings.database_path).execute("SELECT inventory_json FROM players").fetchone()[0])
            assert final['item.array.gathering_basic'] == 1
        finally:
            await runtime.close()
    asyncio.run(run())


def test_basalt_vein_public_iron_combines_with_ironwood_for_pickaxe(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await starter(runtime)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE players SET realm_key='qi_gathering',realm_layer=1 WHERE platform_user_id='gatherer'")
            await move(runtime, clock, '玄武岩径')
            started = await send(runtime, '开始挂机 玄武岩径筛砂 循缝拾铁', 'vein-start')
            assert started.ok, started.message
            clock.advance(hours=8)
            claimed = await send(runtime, '领取挂机', 'vein-claim')
            assert claimed.ok and claimed.data['reward']['item.ore.ironstone'] >= 3, claimed.message
            await move(runtime, clock, '近郊')
            await move(runtime, clock, '铁木林')
            assert (await send(runtime, '开始挂机 铁木林拾材 顺纹取材', 'wood-start')).ok
            clock.advance(hours=6)
            wood = await send(runtime, '领取挂机', 'wood-claim')
            assert wood.ok and wood.data['reward']['item.mat.wood'] >= 3, wood.message
            inventory = json.loads(player(runtime)['inventory_json'])
            operation = next(f'vein-pickaxe-{i}' for i in range(100) if random_quality_bp(f'vein-pickaxe-{i}') == 1000)
            production = await send(runtime, '开始生产 基础矿镐', operation)
            assert production.ok, production.message
            after = json.loads(player(runtime)['inventory_json'])
            assert inventory['item.ore.ironstone'] - after['item.ore.ironstone'] == 2
            assert inventory['item.mat.wood'] - after['item.mat.wood'] == 1
            clock.advance(seconds=30)
            completed = await send(runtime, '领取生产', 'vein-pickaxe-claim')
            assert completed.ok and completed.data['success'], completed.message
            assert json.loads(player(runtime)['inventory_json'])['item.tool.mining_pickaxe'] >= 1
        finally:
            await runtime.close()
    asyncio.run(run())


def test_choice_late_crosses_business_day_but_keeps_frozen_fallback(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await starter(runtime)
            await move(runtime, clock, '百草坡')
            started = await send(runtime, '开始挂机 百草坡采药 辨叶上坡', 'start')
            assert started.ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot = json.loads(connection.execute('SELECT snapshot_json FROM idle_assignments').fetchone()[0])
            clock.advance(days=2, hours=4, seconds=1)
            await runtime.close()
            runtime = create_runtime(data_dir=tmp_path, clock=clock)
            status = await send(runtime, '挂机状态')
            assert status.data['fallback'] and '辨叶上坡' in status.message
            result = await send(runtime, '领取挂机', 'late')
            assert result.ok and result.data['fallback']
            assert result.data['reward'] == snapshot['fallback_reward']
            assert result.data['reward'].get('item.herb.spirit_leaf', 0) == 0
        finally:
            await runtime.close()
    asyncio.run(run())


def test_qq_wilderness_preview_choice_keeps_short_message_contract(tmp_path):
    from nonebot_plugin_xiuxian_3.adapters.message.markdown import send_markdown_message

    class Bot:
        __module__ = 'nonebot.adapters.qq.bot'
        async def send(self, event, message, **kwargs):
            self.message = message
            return {'id': 'reply'}

    class Event:
        __module__ = 'nonebot.adapters.qq.event'

    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await starter(runtime, adapter='qq.official')
            assert (await send(runtime, '前往 百草坡', adapter='qq.official')).code == 'TRAVEL_STARTED'
            clock.advance(minutes=3)
            assert (await send(runtime, '结算移动', adapter='qq.official')).ok
            preview = await send(runtime, '挂机预览 百草坡采药', adapter='qq.official')
            assert preview.ok and len(preview.actions) == 1
            assert '选择扶徒归棚' in preview.message and '选择辨叶上坡' in preview.message
            bot = Bot()
            sent = await send_markdown_message(bot, Event(), preview.message, actions=preview.actions,
                capabilities=('markdown', 'keyboard'), command_prefix='!')
            assert sent.sent_format == 'markdown+keyboard'
            assert '!开始挂机 百草坡采药' in str(bot.message)
            assert '选择扶徒归棚' in preview.message
            assert '开始挂机 百草坡采药 扶徒归棚' in unquote(preview.message)
            fallback = Bot()
            text_sent = await send_markdown_message(fallback, object(), preview.message, actions=preview.actions)
            assert text_sent.sent_format == 'text'
            assert '可发送：开始挂机 百草坡采药' in str(fallback.message)
            assert '选择扶徒归棚（开始挂机 百草坡采药 扶徒归棚）' in str(fallback.message)
            assert 'command:' not in str(fallback.message) and 'mqqapi:' not in str(fallback.message)
            invalid = await send(runtime, '开始挂机 百草坡采药 不存在', 'invalid', adapter='qq.official')
            assert invalid.data['reason'] and invalid.data['subject'] == '百草坡采药 不存在'
        finally:
            await runtime.close()
    asyncio.run(run())
