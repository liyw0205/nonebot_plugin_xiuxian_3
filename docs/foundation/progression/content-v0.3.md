# v0.3 境界内容基线：元婴与心魔

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。

- `content_version`：`content-0.3`
- `rule_version`：`progression-0.3.0`
- 正式开放境界：`nascent_soul`；`nascent_soul_late` 是元婴 L9 圆满内容里程碑键，不是额外境界。十层阈值以 [十层规范](layers.md) 为准。
- 写用例：`progression.breakthrough_nascent_soul`、`event.resolve_heart_demon`、`progression.recover_soul_fatigue`。

## 1. 元婴准入与里程碑

| 内容键 | 前置 | 状态/产出 | 关闭语义 |
|:--|:--|:--|:--|
| `nascent_soul` | 金丹 L10 混元、总修为 `>=58,960`、`foundation_quality>=5,500`、完成 `quest.prepare_nascent_soul` | 可创建元婴突破会话 | v0.3 前为 `locked` |
| `milestone.nascent_soul_late` | 元婴 L9 圆满、总修为 `>=210,000`、任一三界声望 `>=1,000` | 解锁跨界秘境、赛季首领和道统前置 | 不产生境界变化 |
| `event.heart_demon_trial` | 元婴突破失败后自动创建 | 三选一心魔处理；决定疲劳/污染/声望结果 | 只允许按原 operation 结算一次 |

当前运行时在 `progression.advance_layer` 成功进入元婴 L9（或之后的层数），总修为达到
210,000 且任一三界声望达到 1,000 时，原子写入 `milestone.nascent_soul_late` 资格记录。
快照包含达到条件时的境界、层数、总修为、最高三界声望、内容/规则版本和来源 operation；
相同角色只会获得一次，并随晋升 operation 回放原结果。

## 2. 突破会话

材料与成本：`item.pill.soul_condense` 1、`item.soul_crystal` 5、`item.demon_core` 或 `item.beast_blood` 2、灵石 5,000、世界功勋 100。可选 `item.pill.soul_restore` 1 作为心魔保护，只有失败时消耗。

`success_bp = clamp(5500 + foundation_quality//10 + preparation_bp + pity_count*400 - cross_realm_risk_bp, 5500, 9000)`。

| 参数 | 数值 | 说明 |
|:--|--:|:--|
| 道基加成 | 0–1,000 bp | `foundation_quality // 10` |
| 准备度 | 最多 1,200 bp | 匹配功法、三界盟约、宗门仪式、静修地点，每项 +300 bp |
| 跨界风险 | 0 或 400 bp | 在非玄天界地点突破时扣除；完成该界盟约则为 0 |
| 失败保底 | 每次 +400 bp，最多 +1,200 bp | 只在完整心魔结算后记入 |
| 会话超时 | 30 分钟 | 超时进入失败结算，材料不返还，随机不重抽 |

成功时进入 `nascent_soul` L1，`realm_cultivation=0`，获得神魂上限 100、领域能量上限 100、世界功勋 200；不自动授予跨界声望。元婴 L1–L10 门槛以 `layers.md` 为准。

## 3. 心魔失败状态机

```text
preparing -> success
          -> heart_demon_pending -> resolved -> soul_fatigue -> ready
```

失败先消耗必需材料、灵石和世界功勋，保留金丹境内修为 65%（层数保持 L10），并锁定 `heart_demon_pending`。同一失败 operation 重试只返回待处理会话，不能再次扣费或抽取。

心魔选项固定为：

| `choice_key` | 前置/成本 | 结果 |
|:--|:--|:--|
| `heart_demon.face` | 无 | `soul_fatigue` 8 小时；`pity_count +1`；获得 `world_merit` 50 |
| `heart_demon.purify` | `item.pill.soul_restore` 1 | 疲劳 3 小时；`pity_count +1`；污染 -10（最低 0） |
| `heart_demon.bargain` | 魔修或污染 `>=20` | 疲劳 12 小时；污染 +20；下次元婴突破额外 +600 bp，仅一次 |

若超时 24 小时未选，系统按 `heart_demon.face` 自动结算。被暂停角色可查看心魔记录但不能选择；管理员恢复不得改写已存 choice。

## 4. 错误、观测与回滚

- 错误：`QUEST_REQUIREMENT_MISSING`、`REALM_MISMATCH`、`SOUL_MATERIAL_INSUFFICIENT`、`HEART_DEMON_PENDING`、`CROSS_REALM_RISK_BLOCKED`、`SOUL_FATIGUE_ACTIVE`。
- 随机池：`breakthrough.nascent_soul.v0.3`；记录 `roll_bp`、公式输入和内容快照。
- 观测：记录失败原因、心魔 choice、污染/声望/功勋前后值、超时自动结算与会话时长。
- 回滚：关闭 v0.3 后禁止新元婴会话；已有 `heart_demon_pending` 必须按 v0.3 自动结算，不可因关闭而丢失。恢复备份保留会话和 operation 的原版本。

## 5. 开发验收

1. 心魔未结算时再次突破返回 `HEART_DEMON_PENDING`，不扣第二组材料。
2. 每个 choice 仅能结算一次，超时 choice 与手动 choice 互斥。
3. `item.pill.soul_restore` 仅在 `purify` 选择时扣除，不在成功突破或其它失败中扣除。
4. 非玄天界风险、盟约抵消、污染变化和保底都写入同一失败快照。
5. 关闭 v0.3 后，现有元婴玩家可读档与结算旧会话，但不能创建新会话。
