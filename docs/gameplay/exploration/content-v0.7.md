# v0.7 探索内容基线（远古洞天与魔渊深层）

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.7`。

| 系统 | 稳定键 | 参数与结算 |
|:--|:--|:--|
| 远古洞天（`cave.ancient_domain`） | 地点 `status=open`；准入化神 L1 + `item.domain_core`×1 | 入口动作 `explore.ancient_domain` 由本版模式的模式记录闭合 |
| 魔渊深层（`demon.abyss_depths`） | 地点 `status=open`；准入化神 L1 + 魔界声望 3000 | 入口动作 `explore.abyss_depths` 由本版模式的模式记录闭合 |
| 远古洞天探索 | `explore.ancient_domain` | 1200 秒、18 体力、2 精力、每日 2 次、战斗率 60%；奖池 `reward_pool.exploration.ancient_domain`；遭遇 `encounter.cave.ancient_domain` |
| 魔渊深层探索 | `explore.abyss_depths` | 1500 秒、22 体力、3 精力、每日 2 次、战斗率 75%；奖池 `reward_pool.exploration.abyss_depths`；遭遇 `encounter.demon.abyss_depths` |
| 洞天敌人 | `enemy.ancient_domain_warden`（权重 60）、`enemy.ancient_domain_echo`（40） | 均绑定 `cave.ancient_domain`，化神 L1，掉落池 `reward_pool.enemy.void` |
| 深渊敌人 | `enemy.abyss_depth_stalker`（55）、`enemy.abyss_pollution_wraith`（45） | 均绑定 `demon.abyss_depths`，化神 L1，掉落池 `reward_pool.enemy.three_realms` |
| 产物 | 领域核心碎片、神魂晶、灵石；魔核、魔界声望、魔界契约线索 | 全部为既有物品与既有声望/货币，不新增资产类型 |

## 合同

- 两个地点只由 `status` 从 `locked` 改为 `open` 开放；`requirements` 与入边（区域通路）不变，
  开放不新增通路、不改变云舟航线或秘境入场。
- 模式记录必须引用存在的地点、`reward` 奖池与 `encounter_pool`；遭遇候选敌人必须存在、处于
  `active` 且 `location_key` 与模式地点一致（`start_exploration_battle` 的地点绑定校验）。
- 奖励经既有探索结算：开始冻结结果快照（`random_pool` + 种子），结算按 operation 回放，
  重复结算不重复发放；体力/精力/每日次数沿用探索域既有门槛与失败语义，不新增机制。
- 地点开放是内容版本的一部分：旧宿主由 `scripts/seed_migrations.json` 的
  `地图/地点.json` 规则升级（旧 blob 指纹 + provenance），模式/敌人/遭遇池/奖励各有一条规则；
  自定义/未知种子仍按守卫保留、冲突回退。

## 边界

不新增物品、技能、掉落池类型、通路或秘境；不改既有模式数值与既有地点门槛；不引入污染/
失败新机制（沿用既有探索失败与战斗失败语义）。
