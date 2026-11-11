# 寻道图鉴回响

## 范围

本阶段只消费已经开放的玄天近郊、雾隐洞天秘境，以及寻道期的两条闲居路线；不开放
`beast.ancestral_lake`、雾隐洞天二层或其他 locked 图鉴内容，不修改原有境界、门票、
体力、时长、日限、完整奖励和逾时保底。

## 公开来源与玩家路径

1. **近郊寻迹**：角色达到 `qi_sensing` 三层后，从青石镇沿公开路线抵达
   `xuantian.outskirts`，移动结算才算完成第一关。
2. **两页见闻**：第二关开始后，在近郊短历练的真实战斗结算中取得
   `codex.creature.iron_boar`；再持公开取得的基础洞天凭证，在
   `cave.mist_grotto` 完成雾隐秘境首通取得 `codex.instance.mist_grotto`。
   战斗失败、秘境未结算、开始前旧图鉴或他人记录均不算。
3. **守望成册**：两页图鉴取得后，第三关开始并按原寻道期门槛完整领取
   `idle.beast_observation` 与 `idle.tower_watch`。逾时保底、取消、旧安排、他人安排和
   日限不足不替代完整交班。

## 事务与快照

主线开始时冻结正文、目标、奖励、动作和开始前已存在的图鉴键。`codex_discovery` 目标只
查询本人 `codex_entries` 的指定条目，且必须是快照后写入；领取主线与奖励仍走同一 SQLite
事务。内容热更不会改变已开始关卡，奖励写入或 operation ledger 失败时整笔回滚，修复后可用
原 operation 重试；相同 operation 只回放原结果，不重复发奖。

QQ 官方与 OneBot V11 共用 application/repository；玩家入口为 `图鉴回响主线`、
`开始图鉴回响主线 <关卡名>`、`领取图鉴回响主线奖励 <关卡名>`，帮助会指向真实移动、探索、
秘境和闲居命令。
