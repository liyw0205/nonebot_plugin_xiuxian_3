# v0.1 特色玩法内容基线：玄天六类玩法起点

本文件遵守 [版本内容开发合同](../../content-development-contract.md) 与 [特色玩法域](README.md) 的六类合同。`content_version=content-0.1`，`rule_version=specials-0.1.0`。所有结算必须保存路线/任务/楼层/快照/故事节点、随机池、版本和 `operation_id`。本文件定义发布内容合同；当前运行时实现与缺口见[当前开发状态](../../current-status.md)。

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

每角色同时 1 个派遣，接受即冻结风险结果、奖励、开始/结束时间和版本；接受后 60 秒内可取消并全返，之后不可取消。延误时长在接受时固定为原时长的 150%，不改变结果。partial 的堆叠物品产出向下取整减半，名望/信誉减半；取消仍计入当天该任务接受次数，避免通过反复接受/取消重抽风险。`dispatch.town_delivery` 每日最多接受 3 次，其他每日 2 次。失败不扣境界/修为，不触发战斗；所有派遣完成后按任务/角色/业务日唯一增加名望/信誉。木材由近郊采集按 10% 概率产出，见探索 v0.1 内容合同。

## 3. 图鉴收集

| `codex_key` | 类别/首见来源 | 里程碑 |
|:--|:--|:--|
| `codex.place.new_town`、`codex.place.outskirts`、`codex.place.spirit_field` | 寻仙问道或正式抵达/新手引导抵达地点 | `codex.xuantian.place_3`：青石镇名望 +5、解锁额外委托 `town_commission.spirit_leaf` |
| `codex.material.blood_grass`、`codex.material.spirit_leaf`、`codex.material.ironstone`、`codex.material.wood`、`codex.material.array_sand` | 首次获得材料 | `codex.xuantian.materials_5`：名望 +5、药圃路线提示 |
| `codex.creature.wood_rat`、`codex.creature.iron_boar`、`codex.creature.mist_guardian` | 战斗结算 | `codex.xuantian.creature_3`：展示徽记、塔层提示 |
| `codex.path.<path_key>` | 入道选择/竞技场公开对手快照观察 | `codex.paths_6`：六道途百科可读 |

额外委托每次只展示给已领取 `codex.xuantian.place_3` 的玩家，需求灵叶 1，交付奖励为灵石 30、青石镇名望 +4、服务信誉 +2；未解锁时列表隐藏且接受事务拒绝。竞技场仅把双方已公开快照中的道途投影给对局参与者，不暴露其他身份或私有角色资料。

所有里程碑领取 operation 唯一，不给灵石大额包、修为、装备、突破物或属性。

## 4. 试炼塔

| `tower_key` | 楼层 | 准入 | 入场成本/上限 | 首通奖励 |
|:--|:--|:--|:--|:--|
| `tower.mist_trial` | 1–10 | 感气 L1 | 体力 4；每日 5 次 | 每层灵石 10、材料 1；5/10 层给图鉴线索/名望 +5 |
| `tower.mist_trial` | 11–20 | 聚气 L4 | 体力 6；每日 4 次 | 每层灵石 20、材料 1–2；15/20 层给配方线索 |
| `tower.mist_trial` | 21–30 | 筑基 L4 | 体力 8；每日 3 次 | 每层灵石 35、材料 2；25/30 层给洞天路线提示 |

每 5 层为首领；首通奖励按 `tower.mist_trial:<floor>:<player>` 唯一。第 15/20 层配方线索稳定键为
`item.clue.recipe_basic`，第 25/30 层洞天路线提示稳定键为 `item.clue.mist_cave_route`；两者均由
`specials-0.1.2` 塔规则实现。练习每层每周 3 次，只给图鉴观察和低价值材料 0–1，不给修为/突破物。
失败/逃跑不掉层，消耗入场体力与战斗耐久。

## 5. 竞技场

| `arena_mode_key` | 准入 | 次数 | 积分 | 奖励 |
|:--|:--|:--|:--|:--|
| `arena.spar` | 感气 L3、发布或匹配公开快照 | 5/日 | 胜 +25、负 -10、平 +5，最低 0 | 图鉴、名望 +1/胜；无灵石掠夺/修为 |
| `arena.practice` | 感气 L1 | 3/日 | 0 | 战术记录、首次对局图鉴 |

快照有效 7 天；同一对手快照每天最多 2 场计分，第三场转练习。v0.1 不开赛季排名结算，仅记录 `arena_rating` 和公开战术摘要。

## 6. 多结局剧情：`story.xuantian.road`

剧情从 `node.arrival` 开始。发送 `剧情线` 查看进度，`开始剧情` 创建唯一运行记录，
`选择剧情 <merchant|warden|gardener>` 锁定分支，`领取剧情结局` 结算唯一结局包。
同一角色只能完成一个分支；选择锁定后不能改选，也不能通过新建同故事绕过。

| 节点/选择 | 前置/成本 | 旗标/下一节点 |
|:--|:--|:--|
| `node.arrival` | 寻仙问道完成 | 开放三条路；无资产成本 |
| `node.merchant.1..3` / `choice.merchant` | 三条不同已交付城镇委托来源 | 冻结来源/节点快照；进入待领奖 `ending.merchant` |
| `node.warden.1..2` / `choice.warden` | 两场不同已结算战斗胜利，连同 `node.arrival` 共三节点 | 冻结来源/节点快照；进入待领奖 `ending.warden` |
| `node.gardener.1..2` / `choice.gardener` | 两次灵田收获，或两次成功药材派遣，连同 `node.arrival` 共三节点 | 冻结来源/节点快照；进入待领奖 `ending.gardener` |
| `ending.merchant` / `ending.warden` / `ending.gardener` | 对应三个节点完成；单一选择锁定 | 地方名望 +10、对应故事图鉴页、对应居所外观解锁；三者互斥 |

故事规则版本为 `specials-0.1.3`。选择时冻结满足前置的来源 operation ID、已完成节点及版本，
记录进入 `ending_pending`；领奖事务原子写入 `flag.road.<branch>`、
`appearance.home.<branch>`、`codex.story.xuantian.road.<branch>` 与名望。药材派遣仅 `outcome=success`
计数；延误、部分成功、失败、未结算委托/战斗/收获均不满足条件。结局包不含修为、突破材料、
战斗属性或终局资源。

故事选择无材料成本，锁定后不可重选；结局奖励不含修为/突破/装备。v0.1 故事不会写阵营、终局或道途重构旗标。

## 7. 关闭与验收

关闭 v0.1 后停止新挂机、派遣、塔/竞技场对局和故事开始；已运行会话按快照结算，已 pending 奖励 7 天内可领。验收：六类玩法均有文本/按钮同用例、重复 operation 回放、不产生修为或突破捷径、内容关闭不会吞没已锁成本。
