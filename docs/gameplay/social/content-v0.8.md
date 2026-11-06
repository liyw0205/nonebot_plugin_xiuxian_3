# v0.8 社交内容基线：道统路线议事

`docs/gameplay/social/content-v0.6.md` 冻结了 `dao.choose_route` 与 `dao.council_vote`：
宗门等级 6 以上、至少 3 名合道投票、公共功勋 1000、`guard_world/ascend/remain` 三选一、
7 天锁定、周日按多数结算、同票沿用上周。此前仓内没有任何数据、表或命令承接这套规则，
本版把它做成可玩的每周议事。

## 数据合同

`data/社交/道统路线.json`（kind `dao_route`）：

| 键 | 字段 | 值 |
|:--|:--|:--|
| `route.dao_settlement.defaults` | `required_sect_level` | 6 |
| | `required_sect_merit` | 1000（每轮结算扣除） |
| | `required_voters` | 3 |
| | `required_realm` / `required_layer` | `dao_union` / 1 |
| | `vote_period_days` | 7（每周一 00:00 UTC 起算） |
| | `lock_days` | 7（自结算时刻起） |
| | `allow_tie_carryover` | true |

三条路线各自声明固定加成键与上限（`≤ 3000 bp`）：

| 键 | 名称 | 加成 | 值 |
|:--|:--|:--|--:|
| `route.dao_settlement.guard_world` | 守界 | `defense_event_bonus_bp` | 1000 |
| `route.dao_settlement.ascend` | 飞升 | `dao_fruit_trial_bonus_bp` | 1000 |
| `route.dao_settlement.remain` | 留界 | `hall_construction_bonus_bp` | 1500 |

三条路线的数值逐字沿用 v0.6 的「守界三界防御 +1000 bp、飞升道果试炼 +1000 bp、留界据点建设 +1500 bp」。
加载器要求路线集合**恰好**是这三条，缺一条或多一条都拒绝加载，避免「少数路线决定多数结果」。

## 校验与迁移边界

`social/dao_route_content.py` 校验：kind 与键前缀、字段集合、正数、`required_realm` 存在且
`required_layer` 落在该境界层区间、`allow_tie_carryover` 必须是布尔、路线 `bonus` 只允许白名单键、
`value_bp` 上限于 3000、别名唯一、路线集合恰好三条；非法抛 `ContentError` 并在导入期构建。

`社交/道统路线.json` 是新增官方种子，`scripts/seed_migrations.json` 以空 `old_sha256` 登记；
三张新表（`dao_route_cycles`、`dao_route_votes`、`dao_route_state`）用 `CREATE TABLE IF NOT EXISTS`，
旧库无需回填。

## 运行时

- **周期**：`dao_route:<ISO 年>-W<周>`，按 UTC ISO 周（周一 00:00 起、下周一 00:00 止）。
- **投票**：`dao_route_votes` 以 `(cycle_id, sect_id, player_id)` 唯一，一人一周一票；
  投票人须为活跃宗门成员、合道（`dao_union` L1 以上）、宗门等级 ≥6，任一不满足即
  `DAO_ROUTE_REQUIREMENT` 且零写。
- **结算**：每次投票前会先结算该宗门最近一个**已结束**的周期；也可用 `道统结算` 显式触发。
  满 3 票时按多数定线；平票且允许沿用则沿用上周路线并标记 `tie_carryover`；无路线可沿用时本期不定线。
  定线成功即扣除 1000 `sect_merit` 并写入 `locked_until = 结算时刻 + 7 天`。
- **票数不足**：周期以「无路线」状态关闭（扣 0 功勋、不写锁定），因此不会把后续每周投票永久卡死在
  一个永远无法通过的结算上；显式结算会返回 `DAO_COUNCIL_QUORUM_MISSING`。
- **锁定**：`locked_until` 未到期时再次结算返回 `DAO_ROUTE_LOCKED`；本周尚未结束则返回 `DAO_ROUTE_NOT_DUE`。
- 全部写操作单事务 + `operations` 幂等；据点为单服结构，不涉及跨服或玩家间资产转移。

## 命令与呈现

`道统`（别名 `道统议事`）、`道统投票 <守界|飞升|留界>`、`道统结算`。
稳定错误码：`DAO_ROUTE_REQUIREMENT`、`DAO_VOTE_ALREADY_CAST`、`DAO_COUNCIL_QUORUM_MISSING`、
`DAO_ROUTE_LOCKED`、`DAO_ROUTE_NOT_DUE`、`DAO_ROUTE_NOT_FOUND`、`INVALID_DAO_ROUTE_COMMAND`、
`LEDGER_CONFLICT`，失败零写。

QQ 原生 Markdown 的状态页列出三条路线与各自加成，可投票时只挂一个「投票 守界」按钮并附
`道统投票 <线名>` 蓝字预填；OneBot 与纯文本降级为可读命令与「可发送：…」，不暴露稳定键。
`修仙帮助 社交` 追加由内容派生的路线段，不含按钮网格。

## 记录在案的后续项

`hall_construction_bonus_bp` 已在社交 v0.10 接入留界据点：建设项新增 `build_hours`，
开工写入 `dao_hall_constructions`，到期由任何据点读写幂等完成；留界线按 1500 bp 缩短工期
（24 小时太清殿为 75130 秒）。完整合同见 [content-v0.10.md](content-v0.10.md)。
`dao_fruit_trial_bonus_bp` 已在社交 v0.11 接入渡劫试炼结算：飞升路线按 1000 bp 提高
成功试炼的道果进度奖励，结算时读取路线且不冻结开始快照。完整合同见
[content-v0.11.md](content-v0.11.md)。
投票对守界事件的加成仍需在对应事件域读取 `dao_route_state`，本版未改动该域。
