# v0.3 内容包发布基线

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。

```yaml
content_version: content-0.3
rule_version: rules-0.3
release_mode: additive
requires: [content-0.2]
open_realms_added: [nascent_soul]
```

## 1. v0.3 新增开放内容

| kind | 稳定键 | 权威文件 |
|:--|:--|:--|
| milestone | `milestone.nascent_soul_late` | progression v0.3 |
| realm | `nascent_soul` | progression v0.3 |
| location | `demon.abyss_market`、`demon.fallen_ruins`、`beast.ten_thousand_hills`、`beast.shapeshift_sanctum`、`cave.boundary_realm`、`xuantian.war_front` | world v0.3 |
| mode | `explore.demon_abyss`、`explore.beast_hunt`、`explore.boundary_realm` | exploration v0.3 |
| enemy | `enemy.demon_overlord`、`enemy.beast_ancestor`、`enemy.boundary_watcher` | combat v0.3 |
| recipe/item | v0.3 跨界配方、神魂丹、神魂晶、魔核、妖血、界限枪、重构令 | production/items v0.3 |
| quest | `quest.rebuild_path`、`quest.demon_main_1`、`quest.break_void_intro` | events/quests v0.3 |
| event/season | `event.demon_invasion`、`event.beast_trade`、`event.boundary_rift`、`event.heart_demon_trial`、`season.three_realms` | events v0.3 |
| social/economy | `sect.choose_alliance`、`sect_war.*`、`market.trade`、`auction.weekly.*` | social/economy v0.3 |
| livelihood | `permit.demon_trade`、`permit.beast_trade`、`permit.boundary_caravan`、`facility.coop_workshop` | livelihood v0.3 |
| routine/adventures | `ritual.spirit_tree.realm`、`gacha.fate.three_realms`、`story.three_realms.oath`、`bounty.demon_relief`、`instance.secret_realm.boundary_rift` | routine/adventures v0.3 |
| advancement/companions | `progression.retreat.nascent`、`talent.tree.*.tier3`、`item.tempering.realm`、`beast.evolution.realm`、`mount.evolution.realm` | advancement/companions v0.3 |

`quest.rebuild_path`：元婴 L9、三界声望各 1000、完成任意跨界主线 1 条；奖励 `item.token.rebuild_path` 1、开放一次 `paths.rebuild`。`quest.demon_main_1`：魔界声望 200、堕落遗迹引导完成；`quest.break_void_intro`：元婴 L9 圆满前置、完成界隙副本 1 次。

## 2. 发布/回滚检查

跨界材料必须有来源、首次绑定、贸易/拍卖锁定和阵营许可；心魔 pending 会话在发布/关闭期间必须可结算。确认元婴突破、跨界地点、队伍 2–5、三界赛季和重构 token 依赖闭合。

关闭 v0.3 停止新跨界会话、拍卖、赛季计分；允许旧副本/心魔/订单/领奖按快照结算。不得删除元婴、跨界声望或绑定材料历史。