# v0.4 物品内容基线：领域与化神材料

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.4`，`rule_version=items-0.4.0`。领域装备首次获得后绑定 12 小时；绑定计时写实例，不因交易尝试、版本关闭或备份恢复重置。

| `item_key` | 类型/堆叠 | 绑定/交易 | 使用与数值 | 来源 |
|:--|:--|:--|:--|:--|
| `item.soul_seed` | 突破材料，9 | 绑定 | 化神突破必需，开始会话后锁定 | 三界战争、化神委托 |
| `item.domain_core` | 领域材料，9 | 绑定 | 化神突破 1 个；领域选择再需 1 个 | 远古洞天、化神奖励 |
| `item.domain_core_fragment` | 领域碎片，99 | 绑定 | 20 个兑换领域核心；不可交易 | 领域事件/赛季 |
| `item.ancient_fruit` | 丹材，99 | 可交易 | 化神突破 3 个；领域恢复丹材料 | 远古洞天 |
| `item.pill.domain_restore` | 恢复丹，9 | 绑定 | 化神失败时改善裂痕；或裂痕提前恢复消耗 | 化神炼丹 |
| `item.weapon.domain_blade` | 法器，唯一 | 绑定 12h 后可交易 | `domain_power +20`，耐久 10000 bp；领域战 -200 bp | 领域首领 |
| `item.array.domain_guard` | 阵法实例，唯一 | 宗门绑定 | 宗门领域防御 +1500 bp，维护每周 1 核心 | 高阶阵堂 |

`item.domain_core` 不能用于普通装备强化、出售给 NPC 或作为生产替代材料。`domain_guard` 只能在宗门领地部署；宗门解散时进入 7 天受保护回收状态，之后返还最后宗主的绑定仓库，不能静默消失。

掉落池 `loot.domain.boss.v0.4`：古果 55%、领域核心 25%、领域装备 15%、阵法 5%。会话开始保存权重、轮次、贡献和 roll；队伍奖励各自产生 operation，唯一物品按贡献排序并将排序快照保存。

错误：`DOMAIN_ITEM_CONTEXT_INVALID`、`SECT_PERMISSION_DENIED`、`DOMAIN_GUARD_ALREADY_DEPLOYED`、`ITEM_BINDING_ACTIVE`。关闭 v0.4 时停止新掉落/部署；已部署阵法只维护可读和原任务结算。验收：领域核心不能双锁用于突破和选择；贡献排序重放一致；宗门权限拒绝不扣维护物；绑定到期后交易不改来源。