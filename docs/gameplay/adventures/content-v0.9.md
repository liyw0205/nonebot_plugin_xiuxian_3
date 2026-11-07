# v0.9 悬赏目标与奖池多样化

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.9`，
`rule_version=adventures-0.9.0`。本版只做内容扩展：给 45 条悬赏补 6 条中后境界差事，
把此前偏少的 `production_completed`、`public_service_completions`、`dispatch_successes`、
`exploration_battle_wins` 四类目标接入更多境界，并新增两个加权奖池。不改悬赏表结构、
目标进度口径、快照/事务/幂等语义，也不新增物品。

## 1. 新增悬赏

`data/任务/悬赏.json`（kind `bounty`）追加 6 条记录，覆盖筑基至炼虚：

| 悬赏 | `key` | 门槛 | 目标类型与来源 | 数量 | 时限/每日 | 奖池 | 名望键 |
|:--|:--|:--|:--|:--|:--|:--|:--|
| 筑基坊市订单 | `bounty.foundation.workshop_order` | 筑基 L1 | `production_completed`（无 target_key） | 2 | 2 小时 / 1 | `reward_pool.bounty.craft_commission` | `local.xuantian.new_town` |
| 筑基共建差事 | `bounty.foundation.service_round` | 筑基 L4 | `public_service_completions`（无 target_key） | 3 | 4 小时 / 1 | `reward_pool.bounty.service_commission` | `local.xuantian.new_town` |
| 金丹巡守派遣 | `bounty.golden_core.patrol_dispatch` | 结丹 L1 | `dispatch_successes` → `dispatch.golden_core.vein_survey` | 2 | 6 小时 / 1 | `reward_pool.bounty.craft_commission` | `local.xuantian.cloud_city` |
| 元婴遗迹清剿 | `bounty.nascent.ruins_hunt` | 元婴 L1 | `exploration_battle_wins` → `enemy.demon_ruins_scout` | 2 | 8 小时 / 1 | `reward_pool.bounty.service_commission` | `local.demon.abyss_market` |
| 化神界域信使 | `bounty.soul.domain_courier` | 化神 L1 | `dispatch_successes` → `dispatch.soul.domain_relay` | 2 | 8 小时 / 1 | `reward_pool.bounty.craft_commission` | `local.xuantian.domain_front` |
| 虚空档案守望 | `bounty.void.archive_watch` | 炼虚 L1 | `exploration_battle_wins` → `enemy.archive_keeper` | 2 | 12 小时 / 1 | `reward_pool.bounty.service_commission` | `local.xuantian.floating_boat` |

记录沿用既有字段（`quality`、`status: open`、`aliases`、`weight`、`consume_target: false`、
`reward_labels: {}`），并且 `status: open`。两类无来源键的目标（`production_completed`、
`public_service_completions`）的 `target_key` 必须为 null，沿用 v0.7 的按项目/按次去重口径；
带键目标必须解析到已开放的敌人或派遣记录，由 `bounty_definitions` 在验载期校验。

## 2. 新增奖池

`data/奖励/奖励.json` 追加两个 `pool_type: weighted` 奖池，各含 3 条互异结果，
奖励为 `spirit_stones` 加占位 `local_reputation`（接取时由 `reward_map` 的
`reward_key_aliases` 替换为该悬赏冻结的 `reputation_key`）：

| 奖池 | 结果（权重 : 灵石 / 名望） |
|:--|:--|
| `reward_pool.bounty.craft_commission` | 100 : 45 / 3，55 : 65 / 2，20 : 90 / 1 |
| `reward_pool.bounty.service_commission` | 100 : 55 / 4，50 : 80 / 2，25 : 120 / 1 |

`local_reputation` 占位键沿用 v0.1 起既有机制；本版不新增奖励键、不改封顶或资产事务。

## 3. 呈现与进度

`悬赏榜` 仍是 3 槽每日批次，新记录按各自 `weight` 参与 `refresh_bounty_candidates`，
接取时仍只允许一桩进行中悬赏；不新增命令、按钮或帮助段。所有目标的进度计算、
`领取悬赏` 的快照判定、`BOUNTY_REQUIREMENT_MISSING` / `BOUNTY_EXPIRED` 与
operation 回放语义均沿用现行消费者，无新代码路径。

## 4. 验收

`test/test_bounty_variety_content.py` 覆盖：

- 6 条新悬赏的目标类型、来源键、境界门槛、奖池、名望与开放状态；
- 每个带键目标都经 `resolve_dispatch` / 敌人或物品记录解析，无来源键目标确认为 null；
- 两个奖池各有至少 2 条互异且非空结果，且每条引用该池的悬赏都能用确定性种子抽出实发奖励；
- 发布清单钉值 `bounties` 从 45 更新为 51。

回归：`test_bounty_batch.py`、`test_adventures_bounty_settlement.py`、
`test_m9_content_integrity.py`、`test_rewards.py`、`test_documentation.py`。
