# v0.1 探索内容基线：采集、短历练、雾隐洞天与悬赏

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.1`，`rule_version=exploration-0.1.0`。写用例：`exploration.start`、`exploration.settle`、`exploration.cancel`、`bounty.accept`、`bounty.claim`。

## 1. 探索模式

| `mode_key` | 地点/前置 | 时长/成本 | `random_pool` | 保底产出与风险 | 日上限 |
|:--|:--|:--|:--|:--|--:|
| `explore.gather_outskirts` | `xuantian.outskirts`、凡人以上 | 30 秒 / 3 体力 | `gather.outskirts.v0.1` | 止血草 1；额外止血草 0–2、铁石 0–2；10% 训练战 | 12 |
| `explore.trial_outskirts` | 近郊、感气 L2 | 60 秒 / 5 体力 | `trial.outskirts.v0.1` | 修为 40–80、灵石 10–30；20% 遭遇战 | 8 |
| `explore.spring_gather` | 灵泉谷、感气 L2、完成采集引导 | 90 秒 / 6 体力 | `gather.spirit_field.v0.1` | 灵叶 1；额外灵叶 0–1、阵砂 0–1；15% 资源事件 | 6 |
| `explore.mist_grotto` | 雾隐洞天、聚气 L4、会话已进入 | 5 分钟 / 10 体力 | `cave.mist_grotto.v0.1` | 修为 300–500、洞天材料 1–3；25% 精英战 | 2 |

探索开始时扣体力、固定角色/地点/装备/道途/随机池/次数；状态 `created -> running -> settled | expired`，
遭遇时进入 `combat_pending` 并关联 `BattleSession`。只有 `created` 可取消，返还全部体力，不抽池。
`running` 后不可取消；超过结束时间 24 小时由恢复任务结算。战斗遭遇由固定 roll 决定，战斗结果
未结算前探索保持 `combat_pending`，不能二次抽探索奖励；胜利发放冻结基础奖励，失败不发放。

当前遭遇映射：`explore.gather_outskirts` 和 `explore.trial_outskirts` 使用 `enemy.wood_rat`
（短历练最低为感气 L2，铁鬃野猪要求 L3）；`explore.mist_grotto` 使用
`enemy.mist_guardian`；`explore.spring_gather` 当前无战斗遭遇。敌人地点、境界前置、规则版本、
属性与装备均以探索开始快照为准。

各池为离散权重：近郊额外草 0/1/2 权重 35/45/20，铁石 0/1/2 权重 50/35/15；短历练修为 40/60/80 权重 30/45/25，灵石 10/20/30 权重 40/40/20；灵泉额外资源按 0/1 权重 60/40；洞天材料使用 `item.herb.spirit_leaf`/`item.mat.array_sand`/`item.ore.ironstone` 权重 45/30/25。气运只允许按属性文档调整非保底项权重，不能改保底产出或遭遇概率。

## 2. 悬赏轮次

每天 00:00 按业务时区创建 `bounty.daily.<date>`，从下列 3 条固定 offer 中创建，角色最多接取 1 条，接受后奖励/时限快照不随刷新变化：

| `offer_key` | 目标 | 时限 | 奖励 | 失败/过期 |
|:--|:--|:--|:--|:--|
| `bounty.herb` | 获得止血草 5 | 30 分钟 | 修为 80、灵石 30 | 过期无奖励，不回收已获草 |
| `bounty.training` | 战胜 `enemy.training_dummy` 2 次 | 1 小时 | 修为 120、`item.pill.focus_low` 1 | 过期无奖励 |
| `bounty.craft` | 完成任意生产订单 1 次 | 2 小时 | 精力 10、声望 5 | 过期无奖励 |

`bounty.claim` 每 offer/角色唯一；达到目标后重复领奖返回原奖励。悬赏不允许通过管理员直接改进度，数据损坏进入只读诊断。

## 3. 错误、关闭与验收

错误：`EXPLORATION_LOCATION_FORBIDDEN`、`EXPLORATION_QUOTA_EXHAUSTED`、`EXPLORATION_BUSY`、`EXPLORATION_NOT_READY`、`EXPLORATION_COMBAT_PENDING`、`BOUNTY_ALREADY_ACCEPTED`、`BOUNTY_EXPIRED`、`BOUNTY_REWARD_ALREADY_CLAIMED`。

关闭时停止新会话/接取；已有 running/combat_pending 会话按原池结算或恢复任务标记 `expired` 并保留成本/原因。验收：前置/体力不足不扣费；随机与遭遇重放稳定；取消只在 created；战斗失败不发冻结资源；每日上限和悬赏领取并发安全；文本/按钮共享同一用例；QQ/OneBot 跨重启回放一致。
