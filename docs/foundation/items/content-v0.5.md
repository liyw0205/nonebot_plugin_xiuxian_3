# v0.5 物品内容基线：虚空材料与航道装备

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.5`，`rule_version=items-0.5.0`。虚空物品默认首次获得绑定 24 小时；虚空遗迹掉落的绑定装备不能拆解，避免通过拆解绕过地域和赛季供应限制。

| `item_key` | 类型/堆叠 | 绑定/交易 | 用途与限制 | 来源 |
|:--|:--|:--|:--|:--|
| `item.void_crystal` | 材料，99 | 24h 绑定后可交易 | 炼虚突破、虚空加工 | 虚空遗迹 |
| `item.void_anchor` | 航行材料，20 | 可交易 | 航道移动；不足不建会话 | 虚空节点、炼虚奖励 |
| `item.weapon.void_edge` | 法器，唯一 | 24h 绑定 | 空间抗性 +2000 bp，耐久 10000 bp | 界壁首领 |
| `item.armor.phase_robe` | 防具，唯一 | 24h 绑定 | 每日一次虚相免伤 1 回合；触发后记日配额 | 虚实试炼 |
| `item.recipe.void_refinery` | 配方，唯一 | 绑定 | 炼虚突破前置，解锁虚空加工 | 炼虚工坊 |
| `item.void_archive` | 任务物，9 | 绑定 | `quest.break_void` 交付；不可交易/销毁 | 虚空档案遗迹 |
| `item.void_power_crystal` | 消耗品，99 | 绑定 24h | 恢复 `resource.void_power` 50，10 分钟冷却 | `recipe.void.crystal_refine` |
| `item.array.void_route` | 宗门航标，唯一 | 宗门绑定，维护 7 天 | 宗门航道成本 -1，最低仍为 1 锚 | `recipe.array.void_route` |
| `item.array.time_accelerator` | 阵法实例，唯一 | 绑定 7 天 | 一张生产订单时间 -3000 bp；每订单一次 | `recipe.time.accelerator` |

航行锚在 `world.enter_void_route` 通过后才消耗；路线/资源/状态失败时解除锁定。相位袍的触发由战斗 operation 保存，未受到真实伤害不消耗日次数；同一行动重放不再次触发。虚空加工订单使用 `production.void_refine`，原料损耗按道途/配方快照，不能受普通炼器减耗重复叠加。

随机池 `loot.void.ruins.v0.5`：晶体 55%、锚 25%、档案 12%、装备 8%；每周同一角色最多获得 2 件虚空装备实例，达到上限后装备权重转为晶体，转换结果写入奖励快照。

错误：`VOID_ITEM_BINDING_ACTIVE`、`VOID_EQUIPMENT_WEEKLY_CAP`、`VOID_ROUTE_RESOURCE_INSUFFICIENT`、`VOID_RECIPE_NOT_LEARNED`。关闭后停止新掉落/航行/加工，旧订单与航行按版本完成；绑定计时继续。验收：锚失败入口不消耗；装备周上限转换稳定；绑定装备不可拆解；相位袍日触发一次且能重放。