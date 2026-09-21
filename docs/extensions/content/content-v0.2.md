# v0.2 内容包发布基线

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。

```yaml
content_version: content-0.2
rule_version: rules-0.2
release_mode: additive
requires: [content-0.1]
open_realms_added: [golden_core]
registered_placeholders_added: [nascent_soul]
```

## 1. v0.2 新增开放内容

| kind | 稳定键 | 权威文件 |
|:--|:--|:--|
| milestone | `milestone.foundation_late` | progression v0.2 |
| realm | `golden_core` | progression v0.2 |
| location | `xuantian.cloud_city`、`xuantian.cloud_mine`、`xuantian.floating_boat`、`cave.mist_grotto_2`、`xuantian.array_hall` | world v0.2 |
| route | `route.cloud_to_mist2`、`route.cloud_to_abyss_intro`、`route.cloud_return` | world v0.2 |
| mode | `explore.cloud_mine`、`explore.cloud_boat_trial`、`explore.mist_grotto_2` | exploration v0.2 |
| enemy | `enemy.cloud_beast`、`enemy.sect_traitor`、`enemy.mist_elite` | combat v0.2 |
| recipe | `recipe.pill.foundation_guard`、`recipe.pill.core_condense`、`recipe.weapon.cloud_sword`、`recipe.array.mist_barrier`、`recipe.food.cloud_tea` | production v0.2 |
| item | `item.pill.core_condense`、`item.material.cloud_iron`、`item.cave_pass_advanced`、`item.token.faction_seal` 等 v0.2 表项 | items v0.2 |
| quest | `quest.prepare_nascent_soul`、`quest.demon_intro`、`quest.beast_intro` | events/quests v0.2 |
| event/season | `event.cloud_mine_rush`、`event.mist_guardian`、`season.foundation` | events v0.2 |
| market | `market.purchase_order`、`sect.exchange.*` | economy v0.2 |
| livelihood | `facility.mist_field`、`facility.mist_workshop`、`project.new_town.*`、`route.new_town_cloud_city` | livelihood v0.2 |
| routine/adventures | `ritual.spirit_tree.advanced`、`gacha.fate.foundation`、`pass.wayfaring.foundation`、`bounty.cloud_mine`、`instance.secret_realm.cloud_boat` | routine/adventures v0.2 |
| advancement/companions | `progression.retreat.foundation`、`talent.tree.*.tier2`、`item.tempering.core`、`beast.evolution.wood_rat_1`、`mount.evolution.bamboo_deer_1` | advancement/companions v0.2 |

`quest.demon_intro`/`quest.beast_intro` 在 v0.2 必须各有明确的引导目标：完成云舟引导、阅读对应风险说明、提交灵石 100；奖励为对应入口资格和声望 20，**不**发魔核/妖血或开放核心地图。元婴仍为 placeholder。

## 2. 发布检查与迁移

验证 v0.1 键仍可读取；金丹突破材料、云铁/凭证、配方输出、地点准入和任务来源闭合。`foundation_late` 是 milestone，不得以 realm 类型写入角色。市场/求购/宗门库存迁移必须对空库、已有 v0.1 玩家、重复运行三种状态通过。

关闭/回滚：停止新金丹/洞天二层/云舟会话；旧会话按 `content-0.2` 结算。不能将已获得金丹角色或已成交订单删除/降级；仅关闭新内容并恢复备份时的可写状态。