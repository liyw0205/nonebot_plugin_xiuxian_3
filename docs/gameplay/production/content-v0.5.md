# v0.5 生产内容基线：虚空加工与时序建设

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.5`，`rule_version=production-0.5.0`。全部要求炼虚、`item.recipe.void_refinery` 已学习和虚空工坊处于维护状态；每日维护 500 灵石由所有者支付，未支付只拒绝新订单。

| `recipe_key` | 输入 | 精力/时长 | 产出 | 上限/失败 |
|:--|:--|--:|:--|:--|
| `recipe.void.crystal_refine` | 虚晶 3、锚 1 | 25 / 10 分钟 | `item.void_power_crystal` 2（恢复虚力 50） | 每日 4；失败返虚晶 1 |
| `recipe.weapon.void_edge` | 虚晶 5、云铁 10、档案 1 | 35 / 20 分钟 | `item.weapon.void_edge` 1 | 每周 1；失败返 50%，档案不返 |
| `recipe.array.void_route` | 锚 3、阵砂 20、灵石 5000 | 40 / 25 分钟 | `item.array.void_route` 1 | 宗门航标，7 天维护；失败锚不返 |
| `recipe.time.accelerator` | 时间花 5、灵石 1000、虚晶 1 | 30 / 15 分钟 | `item.array.time_accelerator` 1 | 每周 2；每订单一次加速 3000 bp |

虚空加工损耗由 `trait.support.void_refine` 降低 1500 bp，但输入数量最低 1；不得与时序福地重复降低同一订单。虚空装备默认绑定 24 小时，不可拆解。失败工具耐久 -2000 bp、`void_power` -20。

错误：`VOID_WORKSHOP_UNMAINTAINED`、`VOID_RECIPE_NOT_LEARNED`、`VOID_WEEKLY_CAP`、`VOID_ORDER_ALREADY_ACCELERATED`、`VOID_POWER_INSUFFICIENT`。关闭时 processing 订单原版本结算，维护费不追扣。验收：维护 job 不双扣；损耗不为 0；订单加速互斥；周上限正确；档案失败不返还。