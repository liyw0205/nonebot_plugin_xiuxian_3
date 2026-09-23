# v0.6 内容包发布基线

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。

```yaml
content_version: content-0.6
rule_version: rules-0.6
release_mode: additive
requires: [content-0.5]
open_realms_added: [dao_union, tribulation, ascension_ready]
```

## 1. v0.6 新增开放内容

| kind | 稳定键 | 对应快照（总表裁决） |
|:--|:--|:--|
| realm | `dao_union`、`tribulation`、`ascension_ready` | progression v0.6 |
| location/node | `dao.origin_gate`、`tribulation.sky_terrace`、`ascension.heaven_path`、`ascension.left_world_hall`、`location.final_arena`、终局 `node.*` | world/exploration v0.6 |
| enemy | `enemy.dao_trial_avatar`、`enemy.tribulation_heaven`、`enemy.ascension_guardian` | combat v0.6 |
| fruit | 六条 `fruit.*` 道果 | paths v0.6 |
| recipe/item | 道果加工、天劫阵、飞升凭证与所有终局物品 | production/items v0.6 |
| quest/task | `quest.dao_union`、`task.dao_origin.guard/build/teach`、`trial.body_and_mind`、`trial.three_realms`、`trial.dao_choice` | progression/events v0.6 |
| event/season | `event.dao_origin`、`event.heaven_tribulation`、`event.ascension_day`、`season.final_heaven` | events v0.6 |
| social/market | 道统路线、留界据点、`market.dao_fragment` | social/economy v0.6 |
| livelihood | `dao_service.*`、`project.dao_settlement`、`project.archive_library`、`project.ascension_supply` | livelihood v0.6 |
| routine/adventures | `ritual.spirit_tree.dao`、`gacha.fate.dao_echo`、`story.dao_echoes`、`bounty.dao_origin_service`、`instance.secret_realm.dao_origin` | routine/adventures v0.6 |
| advancement/companions | `progression.retreat.dao_union`、`talent.tree.*.tier6`、`item.tempering.dao_service`、`beast.evolution.dao`、`mount.evolution.dao` | advancement/companions v0.6 |

## 2. 终局可达性闭包

最终战要求 `dao_fruit_progress>=1000`、`ascension_merit>=1000`。固定可达来源如下，均按角色/赛季唯一并在各任务 operation 中记录：

| 来源键 | 道果进度 | `resource.ascension_merit` | 上限/条件 |
|:--|--:|--:|:--|
| `trial.body_and_mind` | 100 | 100 | 一次 |
| `trial.three_realms` | 180 | 200 | 一次；另给世界功勋 500 |
| `trial.dao_choice` | 250 | 250 | 一次 |
| `task.dao_origin.guard` | 150 | 150 | 一次，守界任务；另给世界功勋 300 |
| `task.dao_origin.build` | 160 | 150 | 一次，留界建设任务；另给世界功勋 300 |
| `task.dao_origin.teach` | 160 | 150 | 一次，道统传承任务；另给世界功勋 400 |
| `recipe.dao.fruit_fragment` | 100 | 0 | 最多 3 次，需对应碎片来源 |

三试炼 + 三道源任务合计道果 1000、`resource.ascension_merit` 1000；配方是失败保护/额外进度路径，不能突破每赛季进度上限 1300。`resource.ascension_merit` 是唯一资源键，文档不得使用未定义的“飞升功勋”作为独立资源。

## 3. 校验、发布与关闭

发布前验证每个终局门槛的生产者/消费者可达、三榜结局互斥、终局物品禁交易、道果与道途匹配、终局角色隐私。关闭后禁止新合道/试炼/最终战，但已有候选角色仍可完成一次结局；不得删除/重选已锁定道果或改变历史结局。
