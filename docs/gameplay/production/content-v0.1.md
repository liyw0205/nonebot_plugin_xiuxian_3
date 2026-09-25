# v0.1 生产内容基线：三类辅修最小闭环

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.1`，`rule_version=production-0.1.0`。首版开放炼丹、炼器、布阵各一条个人生产闭环；烹饪为生活子类，使用统一订单状态机但不要求主辅修。

## 1. 质量与失败公式

生产预览冻结材料质量、熟练度、工具耐久、地点、配方和 `random_pool=production.<recipe>.v0.1`。质量分：

```text
quality = floor(material_quality*4000/10000)
        + floor(proficiency_bp*3000/10000)
        + floor(tool_durability_bp*2000/10000)
        + random_quality_bp
```

`random_quality_bp` 按 0/500/1000 权重 50/35/15 抽取；质量范围 0–10000。成功阈值 4500；质量 8000 以上才产生高品质标记，首版不额外增加产量。失败返还**每类输入向下取整 50%**、给予生产经验 1、不产生目标成品；工具仍消耗基础耐久。相同 operation 回放同一质量/失败，不重抽。

## 2. 配方表

| `recipe_key` | 辅修/前置 | 输入 | 工具/精力/时长 | 成功产出 | 失败与限制 |
|:--|:--|:--|:--|:--|:--|
| `recipe.pill.healing_low` | `alchemy` 1、聚气或炼丹教学 | `item.herb.blood_grass` 2、`item.food.coarse_spirit_rice` 1 | `item.tool.basic_furnace`，4 精力，30 秒，耐久 -100 bp | `item.pill.healing_low` 1；质量 >=8000 再 +1 | 每日 8；失败返 50% 输入 |
| `recipe.pill.focus_low` | `alchemy` 1、感气 | `item.herb.spirit_leaf` 2、血草 1 | 炉，5 精力，45 秒，耐久 -100 bp | `item.pill.focus_low` 1 | 每日 6 |
| `recipe.pill.foundation_draft` | `alchemy` 2、聚气 | 灵叶 3、阵砂 2、铁石 2 | 炉，8 精力，120 秒，耐久 -100 bp | `item.pill.foundation_draft` 1（绑定） | 每日 3；失败按每类输入 50% 向下返还 |
| `recipe.weapon.wood_sword` | `artifice` 1、聚气 | `item.ore.ironstone` 2、`item.mat.wood` 2 | `item.tool.basic_hammer`，5 精力，60 秒，耐久 -100 bp | `item.weapon.wood_sword` 1，耐久 `8000+quality/5` bp | 每日 4；产出不可低于 8000 耐久 |
| `recipe.array.gathering_basic` | `formation` 1、聚气 | `item.mat.array_sand` 2、灵石 20 | 灵泉谷，6 精力，90 秒 | `item.array.gathering_basic` 1，灵气 +500 bp，24 小时 | 每日 3；失败返阵砂 1、不返灵石 |
| `recipe.food.spirit_rice` | 烹饪教学 | `item.food.coarse_spirit_rice` 2 | 2 精力，15 秒 | `item.food.spirit_rice` 2，恢复体力/精力 5 | 每日 10；失败返灵米 1 |

`item.mat.wood`、`item.array.gathering_basic`、`item.food.spirit_rice` 是本文件首次注册的 v0.1 稳定键：木材来自近郊采集；聚灵阵为绑定 24 小时阵法实例；灵米饭可交易、10 分钟使用冷却。

当前运行时切片开放 `recipe.pill.healing_low`、`recipe.pill.focus_low`、`recipe.pill.foundation_draft`、`recipe.weapon.wood_sword` 和
`recipe.array.gathering_basic` 的个人订单；命令为 `生产预览 <配方>`、`开始生产 <配方>`、
`领取生产` 和 `恢复生产`。炼丹教学完成且选择炼丹辅修的感气角色可以制作低阶疗伤丹和焦点丹；
聚气炼丹辅修角色可以制作绑定的筑基丹，作为筑基突破的正式材料来源；
炼器、布阵仍按表中聚气和地点条件校验。五条配方的其余内容键保留在静态配置中，但未
接入命令入口时不能被当作已开放玩法。

## 3. 订单、委托与取消

个人订单状态：`draft -> locked -> processing -> completed|failed|cancelled -> settled`。创建成功才锁材料/精力/工具；`draft` 取消完全释放，`processing` 不可取消，超时 24 小时由恢复任务按已保存随机结果结算。委托订单在 v0.1 只支持 `recipe.pill.healing_low`、`recipe.weapon.wood_sword`，需要委托人锁报酬、生产者确认后锁材料，细节费用见 economy v0.1。

错误：`RECIPE_NOT_LEARNED`、`PROFESSION_REQUIREMENT_MISSING`、`TOOL_MISSING`、`TOOL_DURABILITY_INSUFFICIENT`、`ENERGY_INSUFFICIENT`、`MATERIAL_INSUFFICIENT`、`PRODUCTION_BUSY`、`RECIPE_DAILY_CAP`。关闭时停止新订单，processing 订单按原版本结算。验收：预览不锁资产；失败返还计算正确；工具耐久/精力只扣一次；质量重放稳定；阵法地点前置正确；委托双方资源锁定原子化。
