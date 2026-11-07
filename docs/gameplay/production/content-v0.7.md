# v0.7 生产内容基线（阵法数据化与第三张护阵）

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.7`。

## 1. 绑定订单阵法加速改为数据派生

`item.array.gathering_basic` 一直声明 `production_duration_multiplier_bp=9000`（`bound_order`），
但唯一生效路径是 `facility_repository._facility_duration_seconds` 里硬编码的键与常量
（`item.array.gathering_basic` 且地点 `cave.mist_grotto_2` 且 `FACILITY_DURATION_BONUS_BP`）。
本版把判定改为读取持有阵法自身声明的效果：

- `items/rules.bound_order_duration_multiplier_bp(inventory)` 遍历背包中数量为正的物品记录，
  取声明了 `production_duration_multiplier_bp`、`scope` 为空或 `bound_order`、且 `0 < value < 10000`
  的阵法，多张同时持有时取最强（值最小）的一张；无匹配返回 `None`。
- `facility_repository` 仍只对绑定订单（`recipe.facility_kind` 非空且玩家位于 `cave.mist_grotto_2`）
  应用，结果为 `max(1, 时长 × (10000 − 倍率) // 10000)`。
- `FACILITY_DURATION_BONUS_BP`（1000 bp）降级为缺省回退：只有未声明该效果但持有
  `item.array.gathering_basic` 的旧数据才使用它，因此现行数值（9000 bp ⇒ −1000 bp）**不变**。
- 该效果类型**不**加入 `items/rules._SUPPORTED_EFFECTS`，`使用` 合同（`restore_choice`、
  `next_cultivation_state_bonus_bp`、`exploration_risk_reduction_bp`、`grant_intro_flags`）不变，
  因此第二张护阵不会被误判为可主动使用物品。

验收：`test/test_array_duration_effect.py` 断言发布数据声明值、无阵法无加成、零数量不算持有、
更强声明值生效且非 `bound_order` 作用域被忽略；`test/test_production.py` 绑定订单用例数值不变。

## 2. 第三张护阵与配方

| `recipe_key` | 道途 | 输入 | 精力/时长 | 成功产出 | 失败返还 |
|:--|:--|:--|:--|:--|:--|
| `recipe.array.war_front_ward` | `formation`、元婴 L1、地点 `xuantian.array_hall` | `item.material.ward_plate` 2、`item.mat.array_sand` 2、灵石 120 | 12 / 240 秒 | `item.array.war_front_ward` 1 | 阵盘残片 1、阵砂 1 |

每日 2 次、成功阈值 6000 bp、高品质阈值 8000 bp、`facility_kind=array`，其余字段沿用
`recipe.array.mist_barrier` 的形状。成品 `item.array.war_front_ward` 声明
`exploration_risk_reduction_bp=600`（地点 `xuantian.war_front`、绑定 12 小时、不可交易），
沿用既有 `使用` 合同：只能在其配置地点布置、同类不叠加（重复布置
`ITEM_EFFECT_ALREADY_ACTIVE`）、探索开始时快照降低对应战斗率。

输入材料 `item.material.ward_plate`（阵盘残片）由 `explore.war_front_patrol` 与
`reward_pool.enemy.war_front` 公开产出，`data/来源/来源.json` 登记其采集/战斗/生产渠道与
`item.array.war_front_ward` 的生产渠道。验收见
`test/test_war_front_ward_and_evolution_codex.py`。

## 边界

不新增物品类型、设施种类、配方类别或职业；不改既有配方数值与既有护阵数值；不改 `使用` 合同或
生产事务/幂等/快照语义。
