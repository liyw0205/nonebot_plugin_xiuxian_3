# v0.4 境界内容基线：化神与领域觉醒

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。

- `content_version`：`content-0.4`
- `rule_version`：`progression-0.4.0`
- 正式开放境界：`soul_transformation`（化神）。L1–L10 阈值和段位以[十层规范](layers.md)为准。
- 写用例：`progression.breakthrough_soul_transformation`、`progression.recover_domain_crack`、`paths.choose_domain`。

## 1. 准入、里程碑与开放状态

| 内容键 | 类型 | 前置条件 | 结果 |
|:--|:--|:--|:--|
| `soul_transformation` | 公共境界 | 元婴 L10 混元、总修为 `>=248,960`、神魂 `>=200`、任一三界声望 `>=2,000`、完成 `quest.soul_transformation` | 创建化神突破会话 |
| `milestone.soul_transformation_late` | 化神圆满里程碑 | 化神 L9 圆满、总修为 `>=720,000`、领域等级 3 | 解锁远古洞天、界壁试炼和领域前线 |
| `quest.soul_transformation` | 突破任务 | 完成三次领域材料委托和一次跨界战斗 | 给予突破许可，不发放境界奖励 |

v0.3 或更低版本读取这些内容时状态为 `locked`，只能展示前置条件；不得扣材料或创建会话。

当前运行时在 `progression.advance_layer` 成功进入化神 L9（或之后的层数），总修为达到
720,000 且领域等级达到 3 时，原子写入 `milestone.soul_transformation_late` 资格记录。
快照冻结境界、层数、总修为、领域等级、内容/规则版本和来源 operation；同一角色只会获得一次，
并随晋升 operation 回放原结果。

## 2. 化神突破：`progression.breakthrough_soul_transformation`

输入：`player_id`、可选 `use_domain_stabilizer`、`operation_id`。创建时锁定角色、元婴状态、神魂、三界声望、装备/道途、地点、材料和 `random_pool=breakthrough.soul_transformation.v0.4`。

| 项目 | 固定值 |
|:--|--:|
| 必需材料 | `item.soul_seed` 1、`item.domain_core` 1、`item.ancient_fruit` 3 |
| 必需资源 | 神魂 200、世界功勋 500、灵石 20,000 |
| 可选保护 | `item.pill.domain_restore` 1；仅在失败时生效 |
| 会话锁 | 10 分钟；状态 `preparing` |
| 基础成功率 | 6,500 bp |
| 神魂准备度 | `(soul_power - 200) * 4` bp，最多 1,000 bp |
| 声望准备度 | `(max_faction_reputation - 2000) // 2` bp，最多 1,000 bp |
| 领域前置加成 | 完成三次领域材料委托 +600 bp |
| 失败保底 | 每次失败 +300 bp，最多 +900 bp |
| 最终夹断 | 6,500–9,000 bp |

`success_bp = clamp(6500 + soul_prepare_bp + reputation_prepare_bp + quest_bp + pity_count*300, 6500, 9000)`。随机保存 `roll_bp`，仅 `roll_bp < success_bp` 成功。

成功：消耗全部材料与资源；进入 `soul_transformation` L1、`realm_cultivation=0`，保留历史修为、失败保底归零；建立空领域槽，`domain_power=100`、`domain_charge_max=150`、`realm_resistance=1000 bp`，并发放 `progression.reward.soul_transformation_entry`：世界功勋 300、`item.domain_core` 1（绑定 24 小时）。

失败：必需材料、功勋、灵石、神魂均消耗；元婴境内修为保留 70%（层数保持 L10）；进入 `domain_crack` 24 小时，领域/跨界深层行动禁用，`pity_count +1`。使用保护丹时修为保留 85%、裂痕缩短为 8 小时。失败不降低境界，不删除元婴技能、道途或声望。

## 3. 化神成长与领域衔接

化神层数 L1–L10 与门槛见 `layers.md`。L9 圆满可执行炼虚前置任务；只有 L10 混元可在 v0.5 创建炼虚突破，v0.4 不开放炼虚结算。

化神 L3（入门完成）角色每天在业务日 00:00 把 `domain_charge` 恢复到 150；未使用的领域能量不跨日累积。领域选择由 `paths.choose_domain` 结算，要求化神 L3、对应首要道途等级 5、`item.domain_core` 1；详见 `foundation/paths/content-v0.4.md`。同一角色只能有一个已激活领域，改选属于后续受控重构，不开放免费重置。

`domain_crack` 期间：普通修炼收益 -15%，拒绝 `domain.*` 技能、领域前线、远古洞天和新领域选择；允许资料、恢复、低风险采集。恢复到期自动完成，或在 `xuantian.domain_front` 消耗 `item.pill.domain_restore` 1、灵石 2,000 提前解除。

## 4. 错误、权限、观测与回滚

- 错误：`REALM_MISMATCH`、`CULTIVATION_INSUFFICIENT`、`SOUL_POWER_INSUFFICIENT`、`FACTION_REPUTATION_INSUFFICIENT`、`QUEST_REQUIREMENT_MISSING`、`DOMAIN_CRACK_ACTIVE`、`MATERIAL_INSUFFICIENT`、`CONTENT_CLOSED`。
- 权限：角色本人；管理员只能使用审计化恢复操作，不能跳过任务或伪造 `roll_bp`。
- 观测：记录神魂/声望/功勋前后值、准备度分项、材料、保护丹、成功率、随机、裂痕期限、快照与版本。
- 回滚：关闭 v0.4 后禁止新化神与领域选择；已 `preparing` 的会话按原版本结算或在未扣费阶段取消；已完成领域和裂痕继续可读/按原规则恢复。恢复备份不可重抽随机。

## 5. 开发验收

1. 声望、神魂、任务、材料任一不足时不扣其它资源。
2. `domain_crack` 期间再次突破或选择领域返回明确错误且不创建第二会话。
3. 保护丹只改变失败保留比例与裂痕时长，不能提高 `success_bp`。
4. 相同 operation 回放同一随机、资源结果和领域初始值；不同输入冲突。
5. 领域能量每日重置只改变 `domain_charge`，不改历史战斗快照或未结算会话。
