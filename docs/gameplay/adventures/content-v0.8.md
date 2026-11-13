# v0.8 悬赏接入闲居目标

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.8`，
`rule_version=adventures-0.8.0`。本版给悬赏新增 `idle_claims` 目标类型，并把 v0.8/v0.9 的闲居
路线接入悬赏闭环：玩家先接取差事，再完成一次指定路线的闲居安排并领取所得，差事即达成。

## 1. 数据合同

`data/任务/悬赏.json`（kind `bounty`）新增三条记录，均复用既有奖池，不新增奖池或物品：

| 悬赏 | `key` | 门槛 | 目标 | 时限/每日 | 奖池 |
|:--|:--|:--|:--|:--|:--|
| 矿区看守差事 | `bounty.idle.mine_watch` | 筑基 L4 | `idle.cloud_mine_watch` 结算 1 次 | 12 小时 / 1 | `reward_pool.bounty.herb_supply` |
| 魔界驿所差事 | `bounty.idle.demon_post` | 元婴 L1 | `idle.demon_trade_post` 结算 1 次 | 12 小时 / 1 | `reward_pool.bounty.demon_relief` |
| 道统据点差事 | `bounty.idle.dao_post` | 合道 L1 | `idle.dao_settlement_watch` 结算 1 次 | 12 小时 / 1 | `reward_pool.bounty.void_anchoring` |

记录沿用既有字段：`quality`、`status: open`、`aliases`、`weight`（70/60/50）、`reputation_key`
（云城 / 魔渊集市 / 道统服务）、`consume_target: false`、`reward_labels: {}`。悬赏目标只要求
该路线的一次结算，不消耗闲居所得；路线本身的门槛（境界、许可、项目参与度、道统）仍由闲居
预览与开始校验。

## 2. 目标类型 `idle_claims`

`adventures/rules.py` 的 `_TARGET_KINDS` 新增 `idle_claims`：

- 必须有 `target_key`，且必须解析到 `data/生活/生活.json` 中已开放的 `record_type: idle_route`
  记录；未知或关闭路线在导入期抛 `ContentError`。
- `target_amount` 为正整数，`consume_target` 必须为 false（只有 `inventory_gain` 可消耗）。

`adventures/repository.py` 在接取时冻结 `baseline_idle_assignment_ids`：该玩家在同一条路线上
已结算（`claimed`/`expired`）的安排编号集合。进度按当前已结算安排中不在基线集合内的条数计算，
上限 `target_amount`。这样接取前完成的旧安排不计入，接取后新完成的安排逐条计入；重复结算同一
安排不会重复计数（幂等由 `idle_assignments` 状态与 operation 保证）。

快照校验要求 `baseline_idle_assignment_ids` 为字符串列表，旧快照缺字段会在读取时按快照校验
失败处理，与既有 `dispatch_successes` 基线语义一致；本版不迁移历史悬赏快照。

## 3. 结算与呈现

`领取悬赏` 仍按冻结快照判定进度、发放奖池与地方名望；进度不足返回既有
`BOUNTY_REQUIREMENT_MISSING`，过期返回 `BOUNTY_EXPIRED`，重复领取与 operation 回放语义不变。
`悬赏榜` 的既有展示字段不变，新记录按原有 3 槽每日批次参与刷新；接取时仍只允许一桩进行中悬赏。

本版不新增命令、按钮或帮助段；`修仙帮助 悬赏` 的既有说明已足以覆盖「接取—完成—领取」流程。

## 4. 验收

`test/test_bounty_idle_claims.py` 覆盖：

- 三条记录的 `target_kind`、`target_key`、门槛、时限与奖池；
- 接取后未结算闲居时进度为 0，`领取悬赏` 返回 `BOUNTY_REQUIREMENT_MISSING`；
- 接取前已结算的路线不计入，接取后新结算一次即达成并领取奖池；
- 同一 operation 回放不重复发奖，重启后进度与领奖保持。

回归：`test_bounty_batch.py`、`test_adventures_bounty_settlement.py`、
`test_m9_content_integrity.py`、`test_documentation.py`。
