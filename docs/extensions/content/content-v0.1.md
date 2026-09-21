# v0.1 内容包发布基线

本文件遵守 [版本内容开发合同](../../content-development-contract.md)，是 `content-0.1` 的发布清单，不是另一个玩法定义来源。

```yaml
content_version: content-0.1
rule_version: rules-0.1
release_mode: additive
requires: []
open_realms: [mortal, qi_sensing, qi_gathering, foundation]
registered_placeholders: [golden_core, nascent_soul]
```

## 1. 开放定义集合

| kind | 必须存在的稳定键 | 权威文件 |
|:--|:--|:--|
| realm | `mortal`、`qi_sensing`、`qi_gathering`、`foundation` | `foundation/progression/content-v0.1.md` |
| path | `body`、`spell`、`device`、`demonic`、`beast`、`support` | `foundation/paths/content-v0.1.md` |
| skill | `skill.basic_attack`、六条 `skill.<path>.*` 首版技能 | `gameplay/combat/content-v0.1.md` |
| location | `xuantian.new_town`、`xuantian.outskirts`、`xuantian.sect_gate`、`xuantian.spirit_field`、`cave.mist_grotto` | `gameplay/world/content-v0.1.md` |
| location_placeholder | `demon.abyss_gate`、`beast.ten_thousand_hills` | `gameplay/world/content-v0.1.md` |
| mode | `explore.gather_outskirts`、`explore.trial_outskirts`、`explore.spring_gather`、`explore.mist_grotto` | `gameplay/exploration/content-v0.1.md` |
| enemy | `enemy.training_dummy`、`enemy.wood_rat`、`enemy.iron_boar`、`enemy.bandit_apprentice`、`enemy.mist_guardian` | `gameplay/combat/content-v0.1.md` |
| recipe | `recipe.pill.healing_low`、`recipe.pill.focus_low`、`recipe.weapon.wood_sword`、`recipe.array.gathering_basic`、`recipe.food.spirit_rice` | `gameplay/production/content-v0.1.md` |
| quest | `quest.first_seeking`、`quest.first_cultivation`、`quest.first_gather`、`quest.first_craft` | `gameplay/events/content-v0.1.md` |
| event | `event.spirit_spring` | `gameplay/events/content-v0.1.md` |
| market | `market.list`、`commission.v0.1` | `gameplay/economy/content-v0.1.md` |
| social | `sect.create`、`master.invite`、`party.exploration_pair` | social v0.1 |
| livelihood | `residence.town_room`、`crop.blood_grass`、`town_commission.*`、`route.new_town_outskirts` | livelihood v0.1 |
| routine | `ritual.checkin.daily`、`ritual.makeup.daily`、`ritual.spirit_tree.harvest`、`gacha.fate.basic`、`pass.wayfaring.v0.1`、`quest.seven_day.v0.1`、`redemption.code` | `gameplay/routine/content-v0.1.md` |
| adventures | `bounty.herb_supply`、`instance.secret_realm.mist_grotto`、`story.mainline.xuantian`、`combat.replay` | `gameplay/adventures/content-v0.1.md` |
| advancement | `progression.retreat.basic`、`talent.tree.body`、`constitution.profile`、`item.tempering.basic_weapon`、`item.refinement.basic_weapon` | `foundation/advancement/content-v0.1.md` |
| companions | `beast.wood_rat`、`mount.bamboo_deer`、`beast.gear.sack_small`、`mount.tack.bamboo_saddle` | `gameplay/companions/content-v0.1.md` |

`golden_core` 和 `nascent_soul` 必须在 schema/内容注册表存在，但 `status=placeholder`，不能作为 v0.1 准入、奖励、地点、配方或可执行 action 的结果。魔界/妖界入口是 `locked`，只能展示条件。

## 2. 跨域前置任务注册

v0.1 只注册任务 `quest.first_*`。`quest.demon_intro`、`quest.beast_intro`、`quest.rebuild_path`、`quest.soul_transformation`、`quest.break_void`、`quest.dao_union` 属于未来版本任务，v0.1 解析为 `locked` 说明，不能被地点或按钮提前执行。

## 3. 发布校验

发布 `content-0.1` 必须校验：

1. 所有上表 `open` 键均存在、类型匹配、版本不高于 0.1；所有 placeholder 不被 open 定义引用为可达前置。
2. 每个可消费 `item.*` 至少有一个可达来源或明确的受控初始/任务来源；每个配方输出存在物品定义。
3. 资质、修炼、探索、生产、战斗、市场、任务奖励和常驻经营的随机池/数值符合所属文档范围；经营结果不得写入修为或突破准备度。
4. 所有写入口在 manifest 中唯一拥有者，文本/按钮/Web 不复制资产规则。
5. dry-run 通过后创建备份，再原子激活；激活失败维持前版本（空环境则不激活）。

## 4. 关闭与回滚

关闭 v0.1 只把 executable 定义设为 `closed`，不删除玩家、物品、operation 或历史快照。回滚前停止新写入，等关键会话结算或标记恢复，恢复备份后运行 schema/operation/内容引用完整性检查。