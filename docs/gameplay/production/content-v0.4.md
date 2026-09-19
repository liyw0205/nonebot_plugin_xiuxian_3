# v0.4 生产内容基线：领域工坊与化神配方

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.4`，`rule_version=production-0.4.0`。化神配方要求领域未裂、对应设施/地点开放；质量 >=8000 才产生非绑定装备，否则成功产出绑定版本。

| `recipe_key` | 前置 | 输入 | 精力/时长 | 产出/质量规则 |
|:--|:--|:--|--:|:--|
| `recipe.pill.domain_restore` | 炼丹 6、化神、炼丹房 | `item.ancient_fruit` 2、神魂晶 2 | 20 / 8 分钟 | `item.pill.domain_restore` 1；每日 2，绑定 |
| `recipe.weapon.domain_blade` | 炼器 6、化神、领域工坊 | 核心 1、云铁 8、古果 1 | 25 / 12 分钟 | `item.weapon.domain_blade`；质量 >=8000 后 12h 绑定再可交易 |
| `recipe.array.domain_guard` | 布阵 6、宗门等级 4、阵堂 | 阵砂 15、核心 1、灵石 3000 | 30 / 15 分钟 | `item.array.domain_guard`；永久宗门绑定 |
| `recipe.fruit.soul_seed` | 灵植 5、祖灵湖灵田 | 祖灵血 2、灵泉水 5 | 15 / 6 小时 | `item.soul_seed` 1；每块灵田 7 天一次 |

失败返还可返材料 50% 向下取整；领域核心不返还，表示领域试制损耗；工具耐久 -1500 bp。`domain.artisan_realm` 只对绑定订单给时间/品质修正，不能降低核心消耗或绕开宗门权限。

错误：`DOMAIN_CRACK_ACTIVE`、`DOMAIN_FACILITY_REQUIRED`、`SECT_LEVEL_INSUFFICIENT`、`SOUL_SEED_PLOT_COOLDOWN`、`RECIPE_QUALITY_INSUFFICIENT`。关闭后停止新工坊订单，宗门阵法继续按维护规则存在。验收：核心失败消耗明确；非绑定装备阈值正确；灵田周冷却幂等；领域修正只作用绑定订单。