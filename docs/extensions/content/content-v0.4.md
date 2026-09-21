# v0.4 内容包发布基线

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。

```yaml
content_version: content-0.4
rule_version: rules-0.4
release_mode: additive
requires: [content-0.3]
open_realms_added: [soul_transformation]
```

## 1. v0.4 新增开放内容

| kind | 稳定键 | 权威文件 |
|:--|:--|:--|
| realm/milestone | `soul_transformation`、`milestone.soul_transformation_late` | progression v0.4 |
| domain | 六条 `domain.*` 领域键 | paths v0.4 |
| location | `cave.ancient_domain`、`demon.abyss_depths`、`beast.ancestral_lake`、`xuantian.domain_front`、`void.portal` | world v0.4 |
| mode/enemy | v0.4 三种探索模式、三种化神首领 | exploration/combat v0.4 |
| recipe/item | 领域恢复丹、领域刃、领域阵、神魂种子及对应物品 | production/items v0.4 |
| quest | `quest.soul_transformation`、`quest.domain_material_commission`、`quest.ancient_domain_line` | events/quests v0.4 |
| event/season | `event.domain_front`、`event.ancient_domain_open`、`event.abyss_depths`、`season.domain_war` | events v0.4 |
| social/market | 领域建筑、`market.domain_material`、领域兑换周 | social/economy v0.4 |
| livelihood | `project.domain_refuge`、`project.abyss_purification`、`project.ancestral_habitat`、`facility.domain_*` | livelihood v0.4 |
| routine/adventures | `ritual.spirit_tree.domain`、`gacha.fate.domain`、`story.domain_rebuild`、`bounty.domain_crack`、`instance.secret_realm.ancient_domain` | routine/adventures v0.4 |
| advancement/companions | `progression.retreat.soul_transformation`、`talent.tree.*.tier4`、`item.tempering.domain`、`beast.evolution.domain`、`mount.evolution.domain` | advancement/companions v0.4 |

任务来源：`quest.soul_transformation` 完成三次领域材料委托和跨界战斗 1 次；`quest.domain_material_commission` 在宗门/领域前线交付核心/古果材料；`quest.ancient_domain_line` 完成远古洞天探索 3 次。任务奖励是许可/绑定材料，不直接发领域选择或化神境界。

## 2. 校验、发布与关闭

发布前验证化神材料的生产者/消费者、领域核心的突破/选择双锁、领域建筑权限、领域裂痕状态和地点门槛。`recipe.fruit.soul_seed` 与 `item.soul_seed` 必须作为不同类型的两个键同时存在。领地/领域容量不能在发布后降低。

关闭后停止新化神/领域/深层探索/领域市场会话；已领域战、建筑施工、订单和奖励按 `content-0.4` 结算。回滚不得删除领域选择、建筑历史、化神角色或已记录裂痕。