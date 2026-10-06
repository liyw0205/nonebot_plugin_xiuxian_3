# 静态数据盘点

本文件是当前设计文档到运行时配置文件的盘点结果。配置由代码只读加载；玩家、
背包、物品实例、任务进度、会话、随机结果和 operation 仍属于数据库运行数据。

## 1. 建议的内容包文件

运行时统一从 `data/内容清单.json` 读取文件清单，不保存内容或规则版本元数据；
配置包的注册状态不决定玩家入口，入口和关闭语义仍由[当前开发状态](current-status.md)
裁决。每个领域文件只保留 `kind` 和 `records` 等业务结构；每条记录统一使用 `key`，
引用仍使用带类型的 `item_key`、`realm_key` 等字段：

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
  冒险/秘境.json
  生产/配方.json
  任务/任务.json
  剧情/故事.json
  事件/事件.json
  奖励/奖励.json
  道历/行卷.json
  生活/生活.json
  灵兽/灵兽.json
  装备/{法器,防具,饰品,成长,词条,工具}.json
  道具/{材料,丹药,功法,凭证}.json
  阵法/阵法.json
```

装备与道具按运行时消费类型拆分，稳定键仍保持全局唯一；不要再维护一份会产生
重复稳定键的 `artifacts.json`。代码通过 `ContentBundle.get(kind, key)` 读取，
不直接依赖文件名或数组下标。

`道历/行卷.json` 以 `kind=wayfaring_pass` 登记 `pass.wayfaring`，提供周期、等级、
日周配额、八种真实来源的分值和逐级奖励。开卷时冻结完整业务快照、奖励名称与地点名望上限；
历史周期不再读取现行数值。固定指令提示保留在领域代码，不写入内容表。

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
- 配方：`recipe.pill.healing_low`、`recipe.pill.focus_low`、`recipe.pill.qi_guard`、
  `recipe.pill.foundation_draft`、`recipe.pill.foundation_guard`、`recipe.weapon.wood_sword`、`recipe.array.gathering_basic`、
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

当前开放功法共 18 部。除表中的 `item.manual.basic_qi` 外，还包括：
`item.manual.sunrise_breath`、`item.manual.cycle_qi`、`item.manual.river_circulation`、
`item.manual.purple_mansion`、`item.manual.earth_root`、`item.manual.cave_mystery`、
`item.manual.starry_core`、`item.manual.nascent_spirit_return`、`item.manual.lotus_soul`、
`item.manual.heaven_observation`、`item.manual.clear_mind`、`item.manual.void_journey`、
`item.manual.void_heart`、`item.manual.dao_union_mysteries`、`item.manual.myriad_return`、
`item.manual.transcendence_tribulation`、`item.manual.ascension_inquiry`。每个开放境界有两
部，配置修行准入和突破加成，并由突破预览/结算及分阶段悬赏消费。

法器和防具各有 447 件，其中各有 15 件通用基准、432 件覆盖六大道途与九个开放境界（每个组合八件）；饰品 108 件，每个道途/境界组合各有两种选择。装备使用 `path_key` 标记构筑取向，并复用品质成长模板；其效果由装备合同和战斗快照结算。除上表和下方版本清单所列基准装备外，本轮新增：

| 类型 | 新增内容键 |
|:--|:--|
| 法器 | 已有 15 件，以及 `data/装备/法器.json` 中按 `item.weapon.<path>.<key>` 注册的 432 件道途/境界装备 |
| 防具 | 已有 15 件，以及 `data/装备/防具.json` 中按 `item.armor.<path>.<key>` 注册的 432 件道途/境界装备 |
| 饰品 | `data/装备/饰品.json` 中按 `item.accessory.<path>.<key>` 注册；攻击、防御、续航、命中闪避、会心与恢复压制等方向各有差异 |

新增装备均配置品质成长模板和战斗属性；悬赏奖池按品质抽取饰品，并按领取者的道途与境界筛选，领取时直接创建装备实例。

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
`item.clue.demon_contract`、`item.clue.demon_abyss_echo`、`item.clue.beast_bloodline`、`item.demon_core`、`item.beast_blood`、
`item.weapon.boundary_spear`、
`item.armor.soul_robe`、`item.token.rebuild_path`、
`item.array.boundary_gate`、`item.contract.beast_pact`。

### v0.4

`item.soul_seed`、`item.ancestral_blood`、`item.spirit_water`、`item.domain_core`、`item.domain_core_fragment`、
`item.ancient_fruit`、`item.pill.domain_restore`、`item.weapon.domain_blade`、
`item.array.domain_guard`、`item.token.construction_coupon`。

### v0.5

`item.void_crystal`、`item.void_anchor`、`item.weapon.void_edge`、
`item.armor.phase_robe`、`item.recipe.void_refinery`、`item.void_archive`、
`item.archive_fragment.alpha`、`item.archive_fragment.beta`、`item.archive_fragment.gamma`、
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
| `境界/晋升.json` | 同境晋升提示与条件里程碑的稳定键、玩家文案、触发境界/层数及资格门槛 | `foundation/progression/layers.md`、`content-data-contract.md` |
| `道途/道途.json` | 六大道途、被动、主动技能和状态资源 | `foundation/paths/content-v0.1.md` |
| `技能/技能.json` | 基础攻击、六大道途在九境各自的稳定攻势与战术备选（108 条）、敌方技能及天劫阶段技能；技能名按招式意象命名，战斗消费器结算爆发、辅御、持续、削弱、蓄力、中毒、灼烧和反伤，高阶备选要求悬赏可得的传承残卷 | `gameplay/combat/content-v0.1.md`、`gameplay/combat/workflow.md` |
| `战斗/实体.json` | 独立战斗实体注册；未接入消费器的召唤机关保持锁定 | `gameplay/combat/content-v0.1.md` |
| `引导/引导.json` | 凡人世界阅读、教学采集和生产教学 | `foundation/player/content-v0.1.md` |
| `地图/地点.json` | 玄天起步区、洞天地点、准入、移动成本 | `gameplay/world/content-v0.1.md` |
| `冒险/秘境.json` | 普通秘境准入、地点、路线、守护敌人、消耗、次数、期限及首通/再入所得 | `gameplay/adventures/README.md` |
| `战斗/敌人.json` | 五个首版敌人和 `enemy.tribulation_heaven` 的阶段配置 | `gameplay/combat/content-v0.1.md`、`gameplay/combat/model.md` |
| `生产/配方.json` | 五条首版生产配方、输入、工具、产出和失败规则 | `gameplay/production/content-v0.1.md` |
| `任务/任务.json` | 四条新手任务、完成条件和奖励引用 | `gameplay/events/content-v0.1.md` |
| `剧情/故事.json` | 玄天之路分支、经历门槛、结局产物与奖励地点引用 | `gameplay/specials/story.md` |
| `剧情/主线.json` | 玄天、领域前线与三界主线章节、前置和结局奖励 | `gameplay/specials/workflow.md` |
| `事件/事件.json` | 灵泉事件和贡献/领奖规则 | `gameplay/events/content-v0.1.md` |
| `奖励/奖励.json` | 首次寻仙、入道、战斗、探索、任务奖励池；金丹突破成功后的青石镇地方名望嘉奖 | 各域 v0.1 内容文件；突破嘉奖由 `reward.breakthrough.golden_core` 引用 |
| `生活/生活.json` | 居所、作物、城镇委托、运输和服务 | `gameplay/livelihood/content-v0.1.md` |
| `灵兽/灵兽.json` | 灵兽、灵骑及其装备定义 | `gameplay/companions/content-v0.1.md` |

`skill.*`、`enemy.*`、`recipe.*`、`quest.*` 和 `event.*` 是内容键；战斗、生产、
探索会话以及奖励抽取结果不能直接写回这些静态文件。

### 当前战斗配置

`技能/技能.json` 和 `战斗/敌人.json` 承载当前技能与敌人内容；具体战斗结算冻结
实际属性、技能和规则参数，不记录无业务用途的版本号，也不按文件名、记录顺序或历史方案
选择规则。天劫阶段边界、技能选择、债务护盾和回放字段以
[战斗模型](gameplay/combat/model.md)与[行动流程](gameplay/combat/workflow.md)为准。

## 5. 已裁决的兼容问题

1. `item.pill.foundation_guard` 只表示 v0.1 筑基失败保护丹；v0.2 宗门商店固定兑换使用
   `sect.exchange.foundation_guard`，正式库存由宗门原料和灵石补给产生，不接收绑定丹药捐献；金丹保护丹统一
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
