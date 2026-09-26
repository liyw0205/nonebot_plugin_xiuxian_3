# v0.6 活动内容基线：道源、天劫与终局赛季

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.6`，`rule_version=events-0.6.1`。

| `event_key` | 时长/前置 | 结算 | 限制 |
|:--|:--|:--|:--|
| `event.dao_origin` | 合道；赛季持续 | 三条道统任务完成计道源贡献 | 每角色每任务一次 |
| `event.heaven_tribulation` | 14 天、渡劫候选 | 每候选一场正式天劫 | 同角色只能参加一次正式轮次 |
| `event.ascension_day` | 赛季后 24h | 展示结局、新篇章入口 | 仅展示，不再改资产 |

`season.final_heaven` 按 `rules.py` 中的 UTC 锚点每 35 天滚动一次，赛季区间为 `[starts_at, ends_at)`。三榜独立：成功飞升结局 +1000；已记录的 `remain_in_world` 留界结局 +800；至少两名成员的终局战成功结算（`won` 或 `remained`）时，每位成员 +50。协作榜计发起者与协助者；失败、过期、取消及单人场次不计分。结局榜以 `endgame_endings.created_at` 为完成时间，协作榜以战斗结算时间为完成时间。留界榜不要求 `settlement.dao_hall` 据点建设；那是独立社交内容，未开放时不阻断已完成的留界结局入榜。

单一角色因结局表唯一约束只能进入飞升榜或留界榜之一；协作榜可与结局榜并存。每榜展示前 10 名，排序为总分降序、首次达成当前总分的时间升序、`SHA-256(season_id + ':' + internal_player_id)` 升序；最后一项只用于确定性破同分，不能展示或持久化到公开快照。公开别名按名次生成 `匿名道友 001` 等序号，不显示道号、角色名、平台 ID 或内部角色 ID。

每榜前 10 名领取对应的展示称号；榜首另获得 `chapter.final_heaven` 新篇章资格。奖励稳定键为 `title.season.final_heaven.ascension`、`title.season.final_heaven.dao`、`title.season.final_heaven.cooperation` 和 `chapter.final_heaven`，不发灵石、修为、战斗属性或可交易高阶物。赛季结束时冻结三榜；领奖窗口为 `[ends_at, ends_at + 7 days)`。榜首资格必须在窗口内由玩家明确领取确认；称号在窗口内可领取，窗口过后由首次赛季读取/领奖触发幂等自动补发。无外部定时器时，冻结和过期补发采用按需物化；已冻结快照不因后续运行数据变化重算。

## 2. 合道与道源任务

| `quest_or_task_key` | 前置/目标 | `dao_fruit_progress` | `resource.ascension_merit` | 限制 |
|:--|:--|--:|--:|:--|
| `quest.dao_union` | 炼虚 perfect；完成一条三界主线、跨服宗门战或等价个人挑战 1 次、交付本职业终局作品 | 0 | 0 | 合道许可；每角色一次，领取时发放绑定道果碎片 12（合道消耗 10，道源门行程消耗 2） |
| `task.dao_origin.guard` | 合道；完成守界防御任务 3 次 | +150 | +150 | 每赛季一次；完成时另给世界功勋 300 |
| `task.dao_origin.build` | 合道；完成留界建设/领域维护任务 3 次 | +160 | +150 | 每赛季一次；完成时另给世界功勋 300 |
| `task.dao_origin.teach` | 合道；完成师徒/道统传承任务 3 次 | +160 | +150 | 每赛季一次；完成时另给世界功勋 400 |

三道源任务与三次天劫试炼合计提供 1000 道果进度和 1000 `resource.ascension_merit`，满足最终战可达性。每项任务目标为 3 次，奖励在第 3 次结算；三项任务的世界功勋奖励合计 1,000。任务完成时在同一 operation 写进度、功勋和 `event.dao_origin` 贡献；重复请求只返回原结果。合道资格的职业作品必须先由炼虚 L10 玩家通过 `recipe.masterwork.<path>` 生产；辅修道途还必须完成三件辅修大师作品并以 `recipe.masterwork.support` 合成。`quest.dao_union` 只消费服务端生产订单成功后进入背包的对应 `item.masterwork.*`，不接受旧终局配方或手工资格标记。

`quest.dao_union` 的资格快照和碎片奖励使用 `content-0.6` / `quests-0.6.1`；三界回响主线证据仍固定要求 `content-0.6` / `adventures-0.6.0`。

展示快照只保存匿名别名、榜单键、名次、分数、赛季 ID 和完成时间；内部领奖索引单独保存数据库角色外键，不进入快照或 DTO。不得保存平台用户 ID、token、私聊数据或角色展示名。错误：`FINAL_RANKING_NOT_FINALIZED`、`FINAL_RANKING_NOT_ELIGIBLE`、`FINAL_RANKING_REWARD_CLAIMED`、`FINAL_RANKING_CLAIM_EXPIRED`。验收：正式天劫唯一；三榜归属正确；匿名展示；赛季奖励不回流普通经济；新篇章确认幂等。

错误：`ENDGAME_EVENT_REQUIREMENT_MISSING`、`HEAVEN_TRIBULATION_ALREADY_ENTERED`、`ASCENSION_DAY_CLOSED`。关闭后已终局角色展示不丢失。验收：正式天劫唯一；三榜归属正确；展示匿名；赛季奖励不回流普通经济；新篇章确认幂等。
