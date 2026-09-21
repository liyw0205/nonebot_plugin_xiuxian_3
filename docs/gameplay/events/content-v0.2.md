# v0.2 活动内容基线：金丹竞赛与筑基金丹赛季

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.2`，`rule_version=events-0.2.0`。所有排行榜按轮次快照生成，不读取赛后实时属性。

## 1. 限时事件

| `event_key` | 时长/开放 | 计分与门槛 | 奖励/领取 |
|:--|:--|:--|:--|
| `event.cloud_mine_rush` | 周六 2 小时，云铁矿区、筑基 | 每云铁 +1；个人最多 50；前 100 排名 | 前 1–3：云铁 20/15/10、`merit` 50/30/20；4–100：云铁 5、功德 10；结束 24h 领 |
| `event.mist_guardian` | 周日 1 小时，洞天二层、金丹 | 雾隐统领伤害每 100 点 +1；贡献 >=30 | `item.pill.core_condense` 1、修为 300；首领击败额外功勋 20 |

事件操作冻结轮次、地点、敌人/采集池、贡献和排名 tie-break（贡献 desc、首次贡献时间 asc、player_id asc）。每角色每轮唯一领奖；未进入奖励范围不创建奖励 operation。

## 2. `season.foundation`

赛季时长 14 天，开始/结束由管理 job 生成 `season.foundation.<season_id>`，赛季积分仅排行，季末清零且不可兑换灵石。

| 榜单 | 积分来源 | 前三奖励 |
|:--|:--|:--|
| `ranking.realm` | 聚气突破 +100、筑基 perfect +30 | `item.pill.golden_core_guard` 3/2/1 |
| `ranking.combat` | 金丹精英胜利 +20 | 云纹剑 1 / 云铁 10 / 云铁 5 |
| `ranking.production` | 已结算成品质量分总和 | 高级配方 1 / 精力药剂 3 / 精力药剂 1 |

每日任务增加：精英战、护基丹生产、宗门任务；每项只由相关 operation 计一次。赛季奖励结束后 24 小时待领；逾期转为绑定功勋 10，不能补发原可交易物。

## 3. 跨界入口引导任务

| `quest_key` | 前置/目标 | 成功产出 | 限制 |
|:--|:--|:--|:--|
| `quest.demon_intro` | 筑基；完成 `route.cloud_to_abyss_intro`、确认魔界风险说明、提交灵石 100 | `access.demon_abyss_gate`、`faction_reputation.demon` 20 | 不发魔核、不开放魔界核心区；每角色一次 |
| `quest.beast_intro` | 筑基；完成妖界史阅读、近郊妖兽观察 1 次、提交灵石 100 | `access.beast_ten_thousand_hills`、`faction_reputation.beast` 20 | 不发妖血、不开放妖界核心区；每角色一次 |

两项任务的确认/提交/奖励均通过 `quest.complete` 单一 operation 结算；重复返回原资格。入口资格只用于 v0.2 锁定入口说明，核心地点仍在 v0.3 才开放。

错误：`SEASON_NOT_ACTIVE`、`SEASON_REWARD_ALREADY_CLAIMED`、`EVENT_RANKING_NOT_FINALIZED`。关闭时冻结积分写入，先生成排名快照再开放领奖。验收：排名 tie-break 稳定；同一精英战不双加分；活动与赛季奖各自唯一；赛后实时变更不影响榜单。
