# v0.5 境界内容基线：炼虚与虚空航行

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。

- `content_version`：`content-0.5`
- `rule_version`：`progression-0.5.0`
- 正式开放境界：`void_refining`（炼虚）。L1–L10 阈值和段位以[十层规范](layers.md)为准。
- 写用例：`progression.breakthrough_void_refining`、`world.enter_void_route`、`progression.recover_void_instability`。

## 1. 准入与开放内容

| 内容键 | 前置条件 | 成功结果 | 状态 |
|:--|:--|:--|:--|
| `void_refining` | 化神 L10 混元、总修为 `>=848,960`、完成 `quest.break_void` | 可创建炼虚突破 | `open` |
| `milestone.void_refining_late` | 炼虚 L9 圆满、总修为 `>=2,500,000`、虚空航道发现 3 条 | 解锁合道前置与跨服宗门战资格 | `open` |
| `quest.break_void` | 完成界壁试炼 3 次、上交虚空档案 1 份 | 给予炼虚许可 | `open` |

`quest.break_void` 的三次界壁试炼按周计数，失败仍计一次参与但不产出虚空档案；每周最多 5 次，避免通过无限试炼刷许可。

当前运行时在 `progression.advance_layer` 成功进入炼虚 L9（或之后的层数），总修为达到
2,500,000 且已发现至少 3 条虚空航道时，原子写入 `milestone.void_refining_late` 资格记录。
快照冻结境界、层数、总修为、航道发现数、内容/规则版本和来源 operation；同一角色只会获得
一次，并随晋升 operation 回放原结果。

## 2. 炼虚突破：`progression.breakthrough_void_refining`

| 项目 | 固定值 |
|:--|--:|
| 必需材料 | `item.void_crystal` 5、`item.void_anchor` 2、`item.recipe.void_refinery` 已学习 |
| 必需资源 | 世界功勋 500、灵石 80,000、领域能量 100 |
| 会话锁 | 15 分钟，`preparing`；地点必须为 `void.first_route`、已结算的 `void.archive_ruins` 或 `cave.time_garden` |
| 基础成功率 | 7,500 bp |
| 航道发现加成 | 每条 +200 bp，最多 600 bp |
| 领域稳定加成 | `domain_power // 10` bp，最多 500 bp |
| 失败保底 | 每次 +250 bp，最多 750 bp |
| 最终夹断 | 7,500–9,200 bp |

`success_bp = clamp(7500 + route_count*200 + min(domain_power//10,500) + pity_count*250, 7500, 9200)`；`random_pool=breakthrough.void_refining.v0.5`。突破开始时冻结路线发现数、领域、地点、装备、道途、材料、资源和随机池。化神角色通过公开界壁试炼和档案航道后会正式抵达 `void.archive_ruins`，该地点是取得炼虚许可后的临时突破落点；炼虚角色仍可在第一航道或时序福地突破。

成功：进入 `void_refining` L1、`realm_cultivation=0`，获得 `void_power=200/200`、`space_resistance=1500 bp`、虚空锚持有上限 20；发放 `progression.reward.void_refining_entry`：`item.void_anchor` 3（绑定 24 小时）、世界功勋 500。炼虚 L1–L10 门槛见 `layers.md`。

失败：材料、功勋、灵石、领域能量全消耗；化神境内修为保留 75%（层数保持 L10），`pity_count +1`；获得 `void_instability` 48 小时。状态期间虚空移动费用 +30%（向上取整），虚空技能禁用，普通三界行动不受影响。没有保护丹；风险通过路线发现、领域与准备度降低，而不是额外付费跳过。

## 3. 虚空资源与行动规则

| 资源/状态 | 上限/恢复 | 用途 | 失败语义 |
|:--|:--|:--|:--|
| `void_power` | 200；业务日恢复至满值 | 虚空技能 20–60/次 | 归零时拒绝技能，不自动借贷 |
| `item.void_anchor` | 背包上限 20 | 航道移动 1–3/次 | 不足时不创建移动会话 |
| `space_resistance` | 软上限 7,500 bp | 降低风暴损失 | 只降低明确损失，不取消所有事件 |
| `void_instability` | 48 小时 | 失败后航行惩罚 | 不能被普通净化清除 |

虚空航行成本：`ceil(route_anchor_cost * (10000 - space_resistance/2) / 10000)`，最少 1 锚；`void_instability` 后最终成本再乘 13000 bp。航行遭遇事件时使用 `random_pool=void.route.<route_key>.v0.5`，开始时保存 pool、roll 和路线快照。

## 4. 关闭、回滚与验收

- 错误：`VOID_QUEST_MISSING`、`VOID_LOCATION_REQUIRED`、`VOID_RESOURCE_INSUFFICIENT`、`VOID_INSTABILITY_ACTIVE`、`VOID_ROUTE_LOCKED`、`CONTENT_CLOSED`。
- 关闭 v0.5：拒绝新炼虚突破和新虚空航行；已在航道的会话按创建版本结算，无法结算时返还尚未消耗的锚并记录 `SETTLEMENT_FAILED`。
- 回滚：恢复前先冻结虚空写入口；恢复后逐条比对航道会话、锚锁定和 operation ledger，不允许因回滚重放随机航行奖励。
- 验收：缺锚不扣任何费用；相同突破 operation 重放相同 roll/结果；风暴损失受抗性下限约束；`void_instability` 不影响非虚空资源结算；航行关闭后旧会话可结算、新会话被拒绝。
