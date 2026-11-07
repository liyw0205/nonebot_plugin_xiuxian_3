# v0.8 探索内容基线（阵堂值守与战线巡防）

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.8`。

两处已开放却此前除单条入口动作外没有任何玩法的地方——`xuantian.array_hall`（阵堂）与
`xuantian.war_front`（魔界战线）——各补一条通用探索模式，驱动引擎、会话、结算、幂等与
失败语义全部沿用探索域既有合同，不新增命令、表、仓库或字段。

| 系统 | 稳定键 | 参数与结算 |
|:--|:--|:--|
| 阵堂值守 | `explore.array_hall_drill`（别名 `阵堂值守`、`校验阵纹`） | 地点 `xuantian.array_hall`，聚气 L1，120 秒、6 体力、每日 5 次，战斗率 25%；奖池 `reward_pool.exploration.array_hall_drill`；遭遇 `encounter.array_hall_drill` |
| 战线巡防 | `explore.war_front_patrol`（别名 `战线巡防`、`巡防战线`） | 地点 `xuantian.war_front`，元婴 L1，300 秒、12 体力、每日 3 次，战斗率 30%；奖池 `reward_pool.exploration.war_front_patrol`；遭遇 `encounter.war_front_patrol` |
| 阵堂敌人 | `enemy.array_hall_sentry`（试阵傀儡） | 绑定 `xuantian.array_hall`，聚气 L1，`stats.agility=9`，掉落池 `reward_pool.enemy.array_hall`，图鉴 `codex.creature.array_hall_sentry` |
| 战线敌人 | `enemy.war_front_vanguard`（魔界先锋军士） | 绑定 `xuantian.war_front`，元婴 L1，`stats.agility=21`，掉落池 `reward_pool.enemy.war_front`，图鉴 `codex.creature.war_front_vanguard` |
| 阵盘残片 | `item.material.ward_plate` | 战线产出材料，来源 `explore.war_front_patrol` 与 `reward_pool.enemy.war_front`，由 `recipe.array.war_front_ward` 消费 |
| 战线护阵 | `item.array.war_front_ward` | `exploration_risk_reduction_bp=600` 于 `xuantian.war_front`，绑定 12 小时；配方 `recipe.array.war_front_ward`（元婴 L1、阵盘残片 2 + 阵砂 2、精力 12、240 秒、每日 2、灵石 120） |
| 图鉴 | `codex.escort.array_hall_drill`、`codex.escort.war_front_patrol`（`challenge` 类）；`codex.creature.array_hall_sentry`、`codex.creature.war_front_vanguard`；`codex.material.ward_plate` | 由探索结算与战斗结算按既有投影记录，不新增条目类型 |

## 合同

- 两条模式记录引用存在的地点、`reward` 奖池与 `encounter_pool`；遭遇候选敌人处于 `active`、
  `location_key` 与模式地点一致（`start_exploration_battle` 的地点绑定校验）。
- 两条奖池各含 ≥3 个互异结果，均正向发放；不引入单档填充。
- 两个地点原有动作（`progression.recover_foundation_shock`、`event.demon_invasion`）保留不变，
  新模式仅追加到各自 `actions`，供 `开始探索` 列表与帮助按地点展示。
- 结算沿用既有探索事务：开始冻结奖池与随机种子，结算按 operation 回放，重复结算不重复发放；
  地点/境界/体力不足不扣资源，次数用尽 `EXPLORATION_QUOTA_EXHAUSTED`，未到期 `EXPLORATION_NOT_READY`。
- 战线护阵沿用既有 `exploration_risk_reduction_bp` 使用合同：只能在其配置地点布置，同类不叠加，
  重复布置 `ITEM_EFFECT_ALREADY_ACTIVE`，探索开始时快照降低对应战斗率。
- 旧宿主由 `scripts/seed_migrations.json` 的对应规则升级（旧 blob 指纹 + provenance）；自定义/未知
  种子仍按守卫保留。

## 边界

不新增地点、通路、物品类型、技能、掉落池类别或秘境；不改既有模式数值与既有地点门槛；
不引入新的污染/失败机制。聚焦证据见 `test/test_array_hall_war_front_exploration.py` 与
`test/test_war_front_ward_and_evolution_codex.py`。
