# v0.13 冒险内容基线（元婴卷第十三章「万兽山·血脉」）

本文件遵守[版本内容开发合同](../../content-development-contract.md)。

元婴配置 `layer_min 1 / layer_max 10 / next_realm soul_transformation`，但主线在
`chapter.12.stage.3`（L9）以 `next_stage_key: null` 结束，**混元 L10 这一层没有任何主线**。
本版补上第十三章三关，把元婴链走到 L10 并在万兽山收束；化神入口属于另一条 story
（`story.mainline.domain_frontier`，由事件旗标 `event.domain_front.joined` 开启），因此本关不跨线链接。

## 关卡

| 关卡 | 名称 | 目标 | 门槛 |
|:--|:--|:--|:--|
| `chapter.13.stage.1` | 入山问脉 | 抵达 `beast.ten_thousand_hills`（`前往 万兽山入口`） | 元婴 L10 |
| `chapter.13.stage.2` | 循血猎兽 | 在 `explore.beast_hunt` 结算中取得 `item.beast_blood`×1 | 元婴 L10 |
| `chapter.13.stage.3` | 守山定契 | 在 `explore.beast_hunt` 中赢得一场遭遇战 | 元婴 L10 |

链路：`chapter.12.stage.3` → `chapter.13.stage.1` → `.2` → `.3`（终点，`next_stage_key` 为空）。
三关同属 `story.mainline.xuantian`，`required_realm=nascent_soul`、`required_layer=10`，并登记进
`_VERTICAL_SLICE_STAGES`，由既有 gate 校验正文长度、章节连续与 `state_changes`。

## 万兽山入口的真实门槛

`beast.ten_thousand_hills` 的地点门槛是 `any_of`：妖界声望 ≥ 200，**或**持有
`access.beast_ten_thousand_hills`。后者来自 `quest.beast_intro`（妖界引导），完整路径为：

1. 在 `xuantian.outskirts` 完成一次 `explore.gather_outskirts` / `explore.trial_outskirts` 结算（近郊见闻）；
2. `阅读妖界史`（记录 `beast_history_read`）；
3. 在近郊 `完成妖界引导`（人物需达筑基 L1，消耗 100 灵石），取得 `access.beast_ten_thousand_hills`。

另外，万兽山只与 `xuantian.floating_boat`（云舟渡口，300 秒 / 12 体力）等妖界地点相连，青石镇侧
没有直连路线，`前往 万兽山入口` 在青石镇会返回 `TRAVEL_ROUTE_INVALID`。因此 13.1 的 `desc` 与
`retry.message` 明写「近郊探索 → 阅读妖界史 → 完成妖界引导 → 从云舟渡口启程」，不把入口说成可直达。

## 数值与结算

| 关卡 | 首通 | 重复 |
|:--|:--|:--|
| 入山问脉 | 灵石 120、服务信誉 6 | 灵石 40 |
| 循血猎兽 | 灵石 90、兽血 1 | 灵石 45 |
| 守山定契 | 灵石 150、血脉线索 1、服务信誉 8 | 灵石 50 |

三关均为 `retry.on_incomplete=keep_running`、冷却 0：未达成目标时不扣首通奖励、不增加尝试次数。
每关写入自身 `activity_events`（`story.mainline.xuantian:chapter.13.stage.N`）。

## 消费者

- `explore.beast_hunt`（万兽山狩猎，元婴 L1、900 秒、20 体力、日限 2、`battle_chance_bp=10000`）由
  既有探索引擎驱动，敌人池 `encounter.beast.ten_thousand_hills`
  （`enemy.beast_guardian` 65 / `enemy.beast_stalker` 35）。
- `reward_pool.exploration.beast_hunt` 真实产出 `item.beast_blood`（45）、`faction_reputation.beast`（30）、
  `item.clue.beast_bloodline`（15）与空结果（10）；兽血是本关目标，线索仍是化神
  `domain_frontier.protect.5` 的同池来源，两者都必须保持可取得。
- 兽血已有下游消费者：`recipe.pill.soul_restore`、`recipe.contract.beast_pact`、`recipe.masterwork.beast`。
- 非妖修且妖界同盟声望为 0 时，`explore.beast_hunt` 会带 1000 bp 跨道途惩罚（既有规则，本版未改）。

## 边界

不新增关卡类型、目标类型、命令、表、字段或随机引擎；第 10–12 章的目标、门槛与奖励不变，
只把 12.3 的 `next_stage_key` 从空改为 13.1。三关全部 `status=open`，未引入跨服、支付或 PvP 内容。
聚焦证据见 `test/test_mainline_beast_chapter.py`、`test/test_yuanying_mainline.py`、
`test/test_mainline_nascent_arc.py` 与 `test/test_seed_migration.py`。
