# 静态数据盘点

本文件是当前设计文档到运行时配置文件的盘点结果。配置由代码只读加载；玩家、
背包、物品实例、任务进度、会话、随机结果和 operation 仍属于数据库运行数据。

## 1. 建议的内容包文件

运行时统一从 `data/内容清单.json` 读取文件清单。当前清单是 `content-0.6` 的活动配置包，
但配置包的注册状态不决定玩家入口；入口和关闭语义仍由[当前开发状态](current-status.md)
裁决。每个领域文件都带
`schema_version`、`content_version`、`rule_version`、`generated_at`、`kind` 和
`records`；每条记录统一使用 `key`，引用仍使用带类型的 `item_key`、`realm_key`
等字段：

```text
data/
  内容清单.json
  境界/境界.json
  道途/道途.json
  技能/技能.json
  战斗/实体.json
  战斗/敌人.json
  引导/引导.json
  地图/地点.json
  生产/配方.json
  任务/任务.json
  事件/事件.json
  奖励/奖励.json
  生活/生活.json
  灵兽/灵兽.json
  装备/{法器,防具,工具}.json
  道具/{材料,丹药,功法,凭证}.json
  阵法/阵法.json
```

装备与道具按运行时消费类型拆分，稳定键仍保持全局唯一；不要再维护一份会产生
重复稳定键的 `artifacts.json`。代码通过 `ContentBundle.get(kind, key)` 读取，
不直接依赖文件名或数组下标。

## 2. 首版 v0.1 必须定义

`docs/extensions/content/content-v0.1.md` 的可执行范围是：

- 境界：`mortal`、`qi_sensing`、`qi_gathering`、`foundation`。
- 占位境界：`golden_core`、`nascent_soul`，必须存在于注册表但状态为
  `placeholder`，不能作为首版可达结果。
- 道途：`body`、`spell`、`device`、`demonic`、`beast`、`support`。
- 地点：`xuantian.new_town`、`xuantian.outskirts`、`xuantian.sect_gate`、
  `xuantian.spirit_field`、`cave.mist_grotto`。
- 锁定地点：`demon.abyss_gate`、`beast.ten_thousand_hills`，只能展示条件。
- 敌人：`enemy.training_dummy`、`enemy.wood_rat`、`enemy.iron_boar`、
  `enemy.bandit_apprentice`、`enemy.mist_guardian`。
- 配方：`recipe.pill.healing_low`、`recipe.pill.focus_low`、
  `recipe.weapon.wood_sword`、`recipe.array.gathering_basic`、
  `recipe.food.spirit_rice`。
- 任务：`quest.first_seeking`、`quest.first_cultivation`、
  `quest.first_gather`、`quest.first_craft`。
- 世界事件：`event.spirit_spring`。

### v0.1 物品清单

来源：`docs/foundation/items/content-v0.1.md`。堆叠上限和绑定规则必须以该表
为准；“唯一”表示使用 `ItemInstance`，不是可无限堆叠的背包数量。

| `item_key` | 类型 | 堆叠/实例 | 绑定/交易 |
|:--|:--|:--|:--|
| `item.food.coarse_spirit_rice` | 食物 | 99 | 可交易 |
| `item.herb.blood_grass` | 药材 | 99 | 可交易 |
| `item.herb.spirit_leaf` | 药材 | 99 | 可交易 |
| `item.ore.ironstone` | 矿材 | 99 | 可交易 |
| `item.mat.wood` | 木材 | 99 | 可交易 |
| `item.mat.array_sand` | 阵材 | 99 | 可交易 |
| `item.food.spirit_rice` | 食物 | 99 | 可交易 |
| `item.array.gathering_basic` | 阵法实例 | 唯一 | 绑定 24 小时 |
| `item.pill.healing_low` | 丹药 | 99 | 可交易 |
| `item.pill.focus_low` | 丹药 | 99 | 可交易 |
| `item.pill.qi_guard` | 突破丹 | 9 | 绑定 |
| `item.pill.foundation_draft` | 突破丹 | 9 | 绑定 |
| `item.pill.foundation_guard` | 突破丹 | 9 | 绑定 |
| `item.manual.basic_qi` | 功法 | 唯一 | 绑定 |
| `item.tool.basic_furnace` | 工具 | 唯一 | 绑定，耐久 2000 bp |
| `item.tool.basic_hammer` | 工具 | 唯一 | 绑定，耐久 2000 bp |
| `item.weapon.wood_sword` | 法器 | 唯一 | 可交易，耐久 10000 bp |
| `item.armor.cotton_robe` | 防具 | 唯一 | 可交易，耐久 10000 bp |
| `item.cave_pass_basic` | 凭证 | 1 | 绑定 |
| `item.token.change_path` | 特殊物品 | 1 | 绑定 |
| `item.token.rename_card` | 改名卡 | 99 | 绑定；再次修改道号时消耗 |
| `item.fragment.dao_name` | 道号碎片 | 99 | 绑定；仅用于展示进度 |
| `item.clue.recipe_basic` | 基础配方线索 | 99 | 绑定；仅用于线索展示 |
| `item.clue.manual_basic` | 基础功法线索 | 99 | 绑定；仅用于线索展示 |
| `item.token.spirit_tree_water` | 灵木水分券 | 99 | 绑定；仅用于灵木浇灌 |

另外，`foundation/advancement/content-v0.1.md` 使用
`item.token.constitution_reset` 作为管理员测试用物品。它不应进入普通掉落池，
但内容校验仍需要将它注册为 `admin_only`，或者在 manifest 中明确声明为测试键。

## 3. 后续版本物品键

以下键来自各版本的权威物品表，先登记为内容注册项；未达到对应版本时必须是
`locked`，不能被首版地点、配方、奖励或按钮引用。

### v0.2

`item.pill.core_condense`、`item.pill.golden_core_guard`、`item.pill.golden_core_restore`、
`item.material.cloud_iron`、`item.weapon.cloud_sword`、`item.armor.cloud_robe`、
`item.cave_pass_advanced`、`item.token.faction_seal`、
`item.array.mist_barrier`、`item.food.cloud_tea`。

### v0.3

`item.pill.soul_condense`、`item.pill.soul_restore`、`item.soul_crystal`、
`item.demon_core`、`item.beast_blood`、`item.weapon.boundary_spear`、
`item.armor.soul_robe`、`item.token.rebuild_path`、
`item.array.boundary_gate`、`item.contract.beast_pact`。

### v0.4

`item.soul_seed`、`item.domain_core`、`item.domain_core_fragment`、
`item.ancient_fruit`、`item.pill.domain_restore`、`item.weapon.domain_blade`、
`item.array.domain_guard`。

### v0.5

`item.void_crystal`、`item.void_anchor`、`item.weapon.void_edge`、
`item.armor.phase_robe`、`item.recipe.void_refinery`、`item.void_archive`、
`item.void_power_crystal`、`item.array.void_route`、
`item.array.time_accelerator`。

### v0.6

`item.tribulation_token`、`item.dao_fruit_fragment`、
`item.masterwork.body`、`item.masterwork.spell`、`item.masterwork.device`、
`item.masterwork.demonic`、`item.masterwork.beast`、`item.masterwork.alchemy`、
`item.masterwork.artifice`、`item.masterwork.formation`、`item.masterwork.support`、
`item.ascension_certificate`、`item.weapon.dao_origin`、
`item.title.ascended`、`item.tribulation_guard`。

## 4. 其他首版静态表

除了物品本体，还需要以下定义表；它们不是玩家运行数据：

| 文件 | 首版内容 | 参考快照（总表裁决） |
|:--|:--|:--|
| `境界/境界.json` | 境界键、中文名、开放状态、L1–L10 阈值、跨境门槛 | `foundation/progression/layers.md`、`content-v0.1.md` |
| `道途/道途.json` | 六大道途、被动、主动技能和状态资源 | `foundation/paths/content-v0.1.md` |
| `技能/技能.json` | 基础攻击、六条道途技能、敌方技能，以及天劫三阶段技能 | `gameplay/combat/content-v0.1.md`、`gameplay/combat/workflow.md` |
| `战斗/实体.json` | 召唤机关等独立战斗实体 | `gameplay/combat/content-v0.1.md` |
| `引导/引导.json` | 凡人世界阅读、教学采集和生产教学 | `foundation/player/content-v0.1.md` |
| `地图/地点.json` | 玄天起步区、洞天地点、准入、移动成本 | `gameplay/world/content-v0.1.md` |
| `战斗/敌人.json` | 五个首版敌人和 `enemy.tribulation_heaven` 的阶段配置 | `gameplay/combat/content-v0.1.md`、`gameplay/combat/model.md` |
| `生产/配方.json` | 五条首版生产配方、输入、工具、产出和失败规则 | `gameplay/production/content-v0.1.md` |
| `任务/任务.json` | 四条新手任务、完成条件和奖励引用 | `gameplay/events/content-v0.1.md` |
| `事件/事件.json` | 灵泉事件和贡献/领奖规则 | `gameplay/events/content-v0.1.md` |
| `奖励/奖励.json` | 首次寻仙、入道、战斗、探索、任务奖励池 | 各域 v0.1 内容文件 |
| `生活/生活.json` | 居所、作物、城镇委托、运输和服务 | `gameplay/livelihood/content-v0.1.md` |
| `灵兽/灵兽.json` | 灵兽、灵骑及其装备定义 | `gameplay/companions/content-v0.1.md` |

`skill.*`、`enemy.*`、`recipe.*`、`quest.*` 和 `event.*` 是内容键；战斗、生产、
探索会话以及奖励抽取结果不能直接写回这些静态文件。

### 当前战斗配置的版本解释

`技能/技能.json` 和 `战斗/敌人.json` 同时承载历史首版键与当前高阶键。文件中的
`content_version` 说明它们属于活动内容包；具体战斗结算使用的 `rule_version` 必须
由战斗开始快照记录，不能用文件名、记录顺序或历史 `content-v0.1.md` 的版本猜测。
天劫三阶段当前使用 `combat-0.6.1`，其阶段边界、技能选择、债务护盾和回放字段以
[战斗模型](gameplay/combat/model.md)与[行动流程](gameplay/combat/workflow.md)为准；
`gameplay/combat/content-v0.6.md` 仍是 `combat-0.6.0` 的历史发布快照。

## 5. 已裁决的兼容问题

1. `item.pill.foundation_guard` 只表示 v0.1 筑基失败保护丹；v0.2 金丹保护丹统一
   改为 `item.pill.golden_core_guard`，突破、配方、奖励、兑换和发布清单均使用新键。
2. 示例装备统一使用正式键 `item.armor.cotton_robe`，不再使用 `item.basic_robe`。
3. 战斗/探索中的“洞天材料 1–3”统一映射为灵叶/阵砂/铁石加权池，运行时配置位于
   `data/奖励/奖励.json` 的雾隐守卫奖励记录。
4. `item.recipe.void_refinery` 是物品表中的配方实例，`recipe.void_refinery` 是配方
   定义；加载器按 `item_key`/`recipe_key` 分开校验，不能用前缀推断类型。

## 6. 运行时落地顺序

1. 先按[完整内容开发总表](content-development.md)裁决稳定键和首版开关。
2. 按 v0.1 清单建立 JSON schema 和内容包，不提前启用 v0.2–v0.6 的可执行效果。
3. 写引用闭合校验：配方输入/输出、奖励物品、敌人技能、地点准入、任务奖励必须
   都能解析到注册表。
4. 运行时通过 `ContentBundle` 读取 `data/内容清单.json` 和领域配置；玩家实例仍由
   数据库保存。
