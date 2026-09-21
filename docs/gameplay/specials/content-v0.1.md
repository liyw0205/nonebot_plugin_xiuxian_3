# v0.1 特色玩法内容基线：玄天六类玩法起点

本文件遵守 [版本内容开发合同](../../content-development-contract.md) 与 [特色玩法域](README.md) 的六类合同。`content_version=content-0.1`，`rule_version=specials-0.1.0`。所有结算必须保存路线/任务/楼层/快照/故事节点、随机池、版本和 `operation_id`。

## 1. 挂机收益

| `idle_route_key` | 准入 | 时长/成本 | 完整领取收益 | 超时最低保底 | 配额 |
|:--|:--|:--|:--|:--|:--|
| `idle.town_errand` | `mortal`、位于新手城 | 2h；无成本 | 灵石 16–24、`local.xuantian.new_town +2` | 灵石 8、名望 +1 | 每日 2 |
| `idle.herb_watch` | active 居所/地块 | 4h；精力 1 | 血草 2–4、灵叶 0–1 | 血草 1 | 每日 1 |
| `idle.workshop_care` | 基础工具或作坊槽 | 3h；工具锁定 | 阵砂 1–3、木材 1–2 | 木材 1 | 每日 1 |
| `idle.route_scout` | 名望 >=20 | 6h；体力 2 | 灵石 25–40、`codex.route.town_road` 线索 1 | 灵石 12 | 每日 1 |

路线池分别为 `idle.town.v0.1`、`idle.herb.v0.1`、`idle.workshop.v0.1`、`idle.route.v0.1`；完整领取在 `duration` 后、最多 24h 内，超过 24h 只给上表保底。`idle.workshop_care` 成功领取工具耐久 -50 bp；其它路线不扣工具。挂机不能与派遣并行，不能产修为、突破物、装备或战斗属性。

## 2. 派遣任务

| `dispatch_key` | 准入 | 时长/成本 | 成功产出 | 风险池/失败 |
|:--|:--|:--|:--|:--|
| `dispatch.town_delivery` | `mortal` | 30m；体力 3 | 灵石 30、名望 +3 | `dispatch.town.v0.1`：成功 75%、延误 15%、partial 10%；partial 灵石 15、名望 +1 |
| `dispatch.herb_search` | 完成采集引导 | 1h；体力 4 | 血草 3–5、灵叶 0–1、图鉴线索 | 成功 70%、partial 20%、failed 10%；failed 返体力 2 |
| `dispatch.workshop_help` | 任一教学服务 | 2h；精力 4、木材 2 | 灵石 45、信誉 +2、阵砂 1–2 | 成功 65%、延误 20%、failed 15%；failed 木材返 1 |

每角色同时 1 个派遣，任务接受后 60 秒可取消并全返；running 后不可取消。`dispatch.town_delivery` 每日 3，其他每日 2。失败不扣境界/修为，不触发战斗；所有派遣完成后按任务/角色/业务日唯一增加名望/信誉。

## 3. 图鉴收集

| `codex_key` | 类别/首见来源 | 里程碑 |
|:--|:--|:--|
| `codex.place.new_town`、`codex.place.outskirts`、`codex.place.spirit_field` | 到达地点 | `codex.xuantian.place_3`：名望 +5、城镇委托额外展示 1 条 |
| `codex.material.blood_grass`、`codex.material.spirit_leaf`、`codex.material.ironstone`、`codex.material.wood`、`codex.material.array_sand` | 首次获得材料 | `codex.xuantian.materials_5`：名望 +5、药圃路线提示 |
| `codex.creature.wood_rat`、`codex.creature.iron_boar`、`codex.creature.mist_guardian` | 战斗结算 | `codex.xuantian.creature_3`：展示徽记、塔层提示 |
| `codex.path.<path_key>` | 入道选择/公开观察 | `codex.paths_6`：六道途百科可读 |

所有里程碑领取 operation 唯一，不给灵石大额包、修为、装备、突破物或属性。

## 4. 试炼塔

| `tower_key` | 楼层 | 准入 | 入场成本/上限 | 首通奖励 |
|:--|:--|:--|:--|:--|
| `tower.mist_trial` | 1–10 | 感气 L1 | 体力 4；每日 5 次 | 每层灵石 10、材料 1；5/10 层给图鉴线索/名望 +5 |
| `tower.mist_trial` | 11–20 | 聚气 L4 | 体力 6；每日 4 次 | 每层灵石 20、材料 1–2；15/20 层给配方线索 |
| `tower.mist_trial` | 21–30 | 筑基 L4 | 体力 8；每日 3 次 | 每层灵石 35、材料 2；25/30 层给洞天路线提示 |

每 5 层为首领；首通奖励按 `tower.mist_trial:<floor>:<player>` 唯一。练习每层每周 3 次，只给图鉴观察和低价值材料 0–1，不给修为/突破物。失败/逃跑不掉层，消耗入场体力与战斗耐久。

## 5. 竞技场

| `arena_mode_key` | 准入 | 次数 | 积分 | 奖励 |
|:--|:--|:--|:--|:--|
| `arena.spar` | 感气 L3、发布或匹配公开快照 | 5/日 | 胜 +25、负 -10、平 +5，最低 0 | 图鉴、名望 +1/胜；无灵石掠夺/修为 |
| `arena.practice` | 感气 L1 | 3/日 | 0 | 战术记录、首次对局图鉴 |

快照有效 7 天；同一对手快照每天最多 2 场计分，第三场转练习。v0.1 不开赛季排名结算，仅记录 `arena_rating` 和公开战术摘要。

## 6. 多结局剧情：`story.xuantian.road`

| 节点/选择 | 前置/成本 | 旗标/下一节点 |
|:--|:--|:--|
| `node.arrival` | 寻仙问道完成 | 开放三条路 |
| `choice.merchant` | 城镇委托 3 次 | `flag.road.merchant`；开放商路故事 |
| `choice.warden` | 战斗胜利 2 次 | `flag.road.warden`；开放近郊守望故事 |
| `choice.gardener` | 灵田收获 2 次或派遣药材成功 2 次 | `flag.road.gardener`；开放药圃故事 |
| `ending.merchant` / `ending.warden` / `ending.gardener` | 对应分支完成 3 个节点 | 名望 +10、图鉴故事页、居所外观；三者互斥 |

故事选择无材料成本，锁定后不可重选；结局奖励不含修为/突破/装备。v0.1 故事不会写阵营、终局或道途重构旗标。

## 7. 关闭与验收

关闭 v0.1 后停止新挂机、派遣、塔/竞技场对局和故事开始；已运行会话按快照结算，已 pending 奖励 7 天内可领。验收：六类玩法均有文本/按钮同用例、重复 operation 回放、不产生修为或突破捷径、内容关闭不会吞没已锁成本。