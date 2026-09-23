# v0.2 境界内容基线：金丹

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。

- `content_version`：`content-0.2`
- `rule_version`：`progression-0.2.0`
- 正式开放境界：`golden_core`；`foundation_late` 是筑基 L9 圆满的**内容里程碑键**，不是额外 `realm_key`。十层阈值以 [十层规范](layers.md) 为准。
- 写用例：`progression.advance_layer`、`progression.breakthrough_golden_core`、`progression.recover_foundation_shock`；全部要求 `operation_id`。

## 1. 开放门槛与内容

| 内容键 | 类型 | 前置条件 | 成功结果 | 失败/关闭 |
|:--|:--|:--|:--|:--|
| `milestone.foundation_late` | 筑基圆满里程碑 | `realm_key=foundation`、`realm_layer>=9`、总修为 `>=10,000` | 解锁云舟、精英悬赏、洞天二层资格检查 | 不消耗资产；v0.2 关闭后仅保留已得资格记录 |
| `golden_core` | 公共境界 | 筑基 L10 混元、总修为 `>=11,960`、`foundation_quality>=4,000`、未虚弱 | 金丹 L1、金丹属性成长、金丹内容准入 | 失败进入 `foundation_shock`；不降境界 |
| `quest.prepare_nascent_soul` | 金丹圆满占位任务 | `golden_core L9`、总修为 `>=50,000` | 剧情记录与元婴预检查提示 | 不能创建元婴突破；v0.3 前状态为 `locked` |

`golden_core` 在 v0.1 仍为 `placeholder`；任何 v0.1 玩家请求必须返回 `CONTENT_CLOSED`，不扣材料或修为。

当前运行时在 `progression.advance_layer` 成功进入筑基 L9（或之后的层数）且总修为达到
10,000 时，原子写入 `milestone.foundation_late` 资格记录。记录冻结达到资格时的境界、层数、
总修为、内容/规则版本和来源 operation；同一角色只会获得一次，并随晋升 operation 回放原结果。

## 2. 金丹突破：`progression.breakthrough_golden_core`

输入：`player_id`、可选保护丹 `use_golden_core_guard`、`operation_id`。开始时冻结角色、`Progression`、属性快照、道途状态、装备、地点、材料、规则和随机池；结算引用 `random_pool=breakthrough.golden_core.v0.2`。

| 项目 | 固定值 |
|:--|--:|
| 必需材料 | `item.pill.core_condense` 1、`item.material.cloud_iron` 3 |
| 可选保护 | `item.pill.golden_core_guard` 1；仅降低失败损失，不增加成功率 |
| 灵石手续费 | 1,000 |
| 行动锁 | 5 分钟，状态 `preparing`；重复请求返回处理中或已结算结果 |
| 基础成功率 | 4,000 bp |
| 道基加成 | `foundation_quality // 5` bp，范围 0–2,000 bp |
| 准备度加成 | 每个已满足项目 +300 bp：金丹级静修地点、匹配功法、宗门护法；最多 900 bp |
| 连续失败保底 | 每次失败 `pity_count +1`，下次 +500 bp，最多 +1,500 bp |
| 最终夹断 | 最低 4,000 bp，最高 8,500 bp |

计算：`success_bp = clamp(4000 + foundation_quality//5 + preparation_bp + pity_count*500, 4000, 8500)`。所有值为整数万分比；随机结果保存为 `roll_bp`，仅当 `roll_bp < success_bp` 成功。

成功：消耗必需材料、手续费和保护丹（若选）；将 `realm_key` 改为 `golden_core`、`realm_layer=1`、`realm_cultivation=0`、保留总修为、`pity_count=0`，并发放 `progression.reward.golden_core_entry`：`merit` 100、`faction_reputation.xuantian` 50。奖励与境界写入同一 operation。

失败：必需材料和手续费消耗；当前筑基境内修为保留 40%，层数保持 L10。未使用保护丹时进入 `foundation_shock` 12 小时；使用保护丹时保留 70% 修为且震荡缩短为 4 小时。两种失败均 `pity_count +1`，不掉落境界、不清除技能或装备。

## 3. 金丹成长与恢复

金丹层数 L1–L10 和修为门槛见 `layers.md`；达到 L9 圆满后可以执行 v0.3 的元婴预检查，达到 L10 混元才可在 v0.3 创建元婴突破。v0.2 不开放元婴结算。

`progression.recover_foundation_shock` 只读检查 `debuff_until`；到期自动解除。玩家可以在玄天阵堂消耗 `item.pill.golden_core_restore` 1 提前解除，额外消耗灵石 200；提前解除不清除失败保底。震荡期间拒绝金丹突破、云舟精英战和洞天二层，普通修炼收益 -20%。

## 4. 错误、权限、观测与回滚

- 错误：`REALM_MISMATCH`、`CULTIVATION_INSUFFICIENT`、`FOUNDATION_QUALITY_LOW`、`BREAKTHROUGH_RECOVERY`、`MATERIAL_INSUFFICIENT`、`LOCATION_REQUIREMENT_MISSING`、`CONTENT_CLOSED`。
- 权限：角色本人；管理员只能经受控恢复用例查看/恢复，不能伪造随机结果。
- 观测：记录 `old_realm`、`new_realm`、`success_bp`、`roll_bp`、`pity_before/after`、材料、费用、保护选项、快照和版本。
- 回滚：关闭 v0.2 后禁止新金丹突破；已处于 `preparing` 的会话按原版本完成或取消并完整返还未提交成本。恢复备份时不得删除已应用的 operation 或重抽 `roll_bp`。

## 5. 开发验收

1. 缺任一材料、灵石或前置时不创建 applied operation，不扣任何资产。
2. 相同 operation 重放同一 `success_bp`、`roll_bp`、材料消耗和结果；输入不同返回 `OPERATION_CONFLICT`。
3. 保护丹只改变失败损失/震荡，不改变成功概率。
4. 震荡期间的受限动作被拒绝；到期或提前恢复后才可重新尝试。
5. v0.1 内容版本请求金丹突破返回 `CONTENT_CLOSED`，不访问 v0.2 材料表。
