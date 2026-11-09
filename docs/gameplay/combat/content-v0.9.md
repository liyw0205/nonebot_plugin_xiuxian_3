# v0.9 战斗内容基线（战利表的 `reward_refs` 消费者）

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.9`。

`combat_content.py` 一直在校验 `enemy.reward_refs`，但它的模块说明也写明了当时的边界：
运行时仍冻结内联的 `combat_profile.reward`，`reward_refs` 只做引用校验，"直到后续消费者显式采纳"。
本版就是那个消费者。

## 采纳范围

| 敌人 | 声明表 | 行为 |
|:--|:--|:--|
| `enemy.wood_rat` | `reward.battle.wood_rat` | 修为 10 + 止血草 0–1 |
| `enemy.iron_boar` | `reward.battle.iron_boar` | 修为 30 + 铁石 1 + 灵石 8 |
| `enemy.bandit_apprentice` | `reward.battle.bandit_apprentice` | 灵石 20 + 修为 60 +（20%）凝神丹 1 |
| `enemy.mist_guardian` | `reward.battle.mist_guardian` | 修为 160 + 加权材料 1–3 |

未声明 `reward_refs` 的敌人行为完全不变（仍用内联 `combat_profile.reward`）。
`enemy.iron_boar` 的战利表此前无人可读：该记录只有 `reward_refs` 而没有 `combat_profile`，
运行时因此回落到代码内常量；现在代码内敌人也会读取内容声明的战利表。

## 后续补充（2026-11-10）：剩余代码持有敌人已内容化

本版只让"代码内敌人也能读内容战利表"，但仍有三条记录**没有 `combat_profile`**，于是它们的
`stats` 虽然在内容里写了却不生效，改内容会被静默忽略（`enemy_definition` 回落到
`combat/rules.py` 的 `ENEMIES` 常量）。现已补齐，**数值一字未改**：

| 敌人 | 现状 | 说明 |
|:--|:--|:--|
| `enemy.iron_boar` | 补 `agility: 8` + `combat_profile.random_pool_key` | 内容 stats 原先缺 `agility`（代码内是 8） |
| `enemy.beast_guardian` | 补 `combat_profile.random_pool_key` | 万兽山守山兽，7500/480/22/24 不变 |
| `enemy.tribulation_heaven` | 补 `combat_profile.random_pool_key` | 三劫天尊，150000/5500/1600/650 不变；`phases` 与 `automatic_phase_selection` 仍由内容驱动 |

来源划分现在是：62 条敌人记录中 **50 条**声明 `combat_profile`（内容持有），**12 条**
`enemy.void_spire.*` 由 `data/特殊/虚空塔.json` 经 `enemy_definition` 的专属分支解析，因此不需要
`combat_profile`。`test_enemy_content_parity.py` 钉住三件事：这三条内容化前后
`(max_hp, attack, initiative, agility, skill_key, label, location_key, reward, reward_refs,
random_pool, required_realm, required_layer)` 完全相同；虚空塔敌人仍从塔内容解析；以及把
`enemy.beast_guardian.stats.hp` 改成 1 后，战斗快照里的 `max_hp` 必须真的是 1（内容编辑确实生效）。

## 结算规则

- **冻结**：战斗开始时按 `battle operation_id` 作为种子一次性掷定，写入战斗快照的 `reward`；
  同一个 operation 重放得到同一份战利，`领取战斗奖励` 仍走既有幂等事务。
- **`chance_bp`**：条目级概率门（bp，0–10000）。`reward.battle.bandit_apprentice` 的凝神丹为
  2000 bp，即 20%。
- **`material_pool`**：记录级加权材料池，`selection=one_weighted` 每次只取一种，
  数量取 `quantity_range`；`reward.battle.mist_guardian` 为灵叶 45 / 阵砂 30 / 铁石 25，数量 1–3。
- **币种**：`kind=currency` 只接受 `currency.spirit_stone`，结算为 `spirit_stones`；其它币种报错。
- **失败关闭**：未知 `kind`、缺键、`chance_bp` 越界、`selection` 非 `one_weighted`、
  非正权重、缺数量规格，一律抛 `RewardContentError`，不静默少发。

## 数据一致性

`enemy.bandit_apprentice` 原先在 `combat_profile.reward` 里另有一份 `{"spirit_stones": 6}`，
与本表（灵石 20）冲突。本版清空该内联副本，使这份记录只有一个来源。
该文件的 `content-v*` 基线见 [content-v0.8.md](content-v0.8.md)。

## 边界

不新增敌人、技能、奖池或表；不改任何敌人的血量/攻击/技能/遭遇池；不改既有奖池权重。
聚焦证据见 `test/test_battle_reward_refs.py`。
