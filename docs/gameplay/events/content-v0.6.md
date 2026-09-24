# v0.6 活动内容基线：道源、天劫与终局赛季

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.6`，`rule_version=events-0.6.0`。

| `event_key` | 时长/前置 | 结算 | 限制 |
|:--|:--|:--|:--|
| `event.dao_origin` | 合道；赛季持续 | 三条道统任务完成计道源贡献 | 每角色每任务一次 |
| `event.heaven_tribulation` | 14 天、渡劫候选 | 每候选一场正式天劫 | 同角色只能参加一次正式轮次 |
| `event.ascension_day` | 赛季后 24h | 展示结局、新篇章入口 | 仅展示，不再改资产 |

`season.final_heaven` 持续 35 天，三榜独立：飞升成功 +1000、留界道统完成 +800、协作终局战每次 +50。单一角色只能进入飞升或留界榜之一；协作榜可与其结局榜并存。赛季奖励只给称号、展示物和新篇章资格，不给灵石/可交易高阶物。

## 2. 合道与道源任务

| `quest_or_task_key` | 前置/目标 | `dao_fruit_progress` | `resource.ascension_merit` | 限制 |
|:--|:--|--:|--:|:--|
| `quest.dao_union` | 炼虚 perfect；完成一条三界主线、跨服宗门战或等价个人挑战 1 次、交付本职业终局作品 | 0 | 0 | 合道许可；每角色一次 |
| `task.dao_origin.guard` | 合道；完成守界防御任务 3 次 | +150 | +150 | 每赛季一次；完成时另给世界功勋 300 |
| `task.dao_origin.build` | 合道；完成留界建设/领域维护任务 3 次 | +160 | +150 | 每赛季一次；完成时另给世界功勋 300 |
| `task.dao_origin.teach` | 合道；完成师徒/道统传承任务 3 次 | +160 | +150 | 每赛季一次；完成时另给世界功勋 400 |

三道源任务与三次天劫试炼合计提供 1000 道果进度和 1000 `resource.ascension_merit`，满足最终战可达性。每项任务目标为 3 次，奖励在第 3 次结算；三项任务的世界功勋奖励合计 1,000。任务完成时在同一 operation 写进度、功勋和 `event.dao_origin` 贡献；重复请求只返回原结果。合道资格的职业作品必须先由炼虚 L10 玩家通过 `recipe.masterwork.<path>` 生产；辅修道途还必须完成三件辅修大师作品并以 `recipe.masterwork.support` 合成。`quest.dao_union` 只消费服务端生产订单成功后进入背包的对应 `item.masterwork.*`，不接受旧终局配方或手工资格标记。

展示快照字段：角色展示名、结局键、赛季 ID、奖励摘要、完成时间；严禁保存平台用户 ID、token 或私聊数据。赛季结束冻结计分、生成榜单、开放 7 天领奖；结束后未领展示物自动授予，资格类奖励仍需玩家确认以开启新篇章。

错误：`ENDGAME_EVENT_REQUIREMENT_MISSING`、`HEAVEN_TRIBULATION_ALREADY_ENTERED`、`FINAL_RANKING_NOT_FINALIZED`、`ASCENSION_DAY_CLOSED`。关闭后已终局角色展示不丢失。验收：正式天劫唯一；三榜归属正确；展示匿名；赛季奖励不回流普通经济；新篇章确认幂等。
