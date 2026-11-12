from __future__ import annotations

import asyncio
import json
import sqlite3
from urllib.parse import unquote

import pytest

from nonebot_plugin_xiuxian_3.runtime import create_runtime
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
            started = await send(runtime, f'开始挂机 百草坡采药 {choice}', 'start')
            assert started.ok, started.message
            assert choice in started.message
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
        try:
            await starter(runtime)
            await move(runtime, clock, '百草坡')
            assert (await send(runtime, '开始挂机 百草坡采药 扶徒归棚', 'start-cancel')).ok
            cancelled = await send(runtime, '取消挂机', 'cancel')
            assert cancelled.data['refunded'] == {'stamina': 3, 'energy': 1}
            assert (await send(runtime, '开始挂机 百草坡采药 辨叶上坡', 'start')).ok
            clock.advance(hours=4)
            claims = await asyncio.gather(send(runtime, '领取挂机', 'claim-a'), send(runtime, '领取挂机', 'claim-b'))
            assert sum(c.ok for c in claims) == 1
            assert {c.code for c in claims} <= {'IDLE_CLAIMED', 'IDLE_NOT_FOUND', 'IDLE_ALREADY_SETTLED'}
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM operations WHERE operation_name='specials.claim_idle'").fetchone()[0] == 1
        finally:
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
