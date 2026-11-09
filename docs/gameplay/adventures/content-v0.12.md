# v0.12 冒险内容基线（元婴卷第十章–第十二章「北渡问契」）

本文件遵守[版本内容开发合同](../../content-development-contract.md)。

主线此前从 `chapter.9.stage.3`（金丹三层，`next_stage_key` 为空）直接跳到化神的
`domain_frontier.guard.1`，元婴整段没有主线。本版补上第十章至第十二章共九关，把玄天卷从云城
经云舟渡口接到魔渊、堕落遗迹与万兽山，再由归舟回到青石镇结卷。

## 关卡

| 关卡 | 名称 | 目标 | 门槛 |
|:--|:--|:--|:--|
| `chapter.10.stage.1` | 云城问舟 | 抵达 `xuantian.cloud_city`（`前往 云城`） | 元婴 L1 |
| `chapter.10.stage.2` | 渡口候船 | 抵达 `xuantian.floating_boat`（`前往 云舟渡口`） | 元婴 L2 |
| `chapter.10.stage.3` | 云舟北渡 | 抵达 `demon.abyss_gate`（`登上云舟 魔界引导` + `结算云舟`） | 元婴 L3 |
| `chapter.11.stage.1` | 入门问契 | 取 `access.demon_abyss_gate` 后抵达 `demon.fallen_ruins` | 元婴 L4 |
| `chapter.11.stage.2` | 契阁残页 | 在 `explore.demon_abyss` 结算中取得 `item.clue.demon_contract`×1 | 元婴 L5 |
| `chapter.11.stage.3` | 遗迹守卫 | 在 `explore.demon_abyss` 中赢得一场遭遇战 | 元婴 L6 |
| `chapter.12.stage.1` | 门备材料 | 在 `explore.demon_threshold` 结算中取得 `item.demon_core`×1 | 元婴 L7 |
| `chapter.12.stage.2` | 归舟回城 | 乘返程云舟抵达 `xuantian.cloud_city` | 元婴 L8 |
| `chapter.12.stage.3` | 回镇结卷 | 抵达 `xuantian.new_town`（`前往 青石镇`） | 元婴 L9 |

链路：`chapter.9.stage.3` → `chapter.10.stage.1` → … → `chapter.12.stage.3`（终点，
`next_stage_key` 为空）。九关同属 `story.mainline.xuantian`，`required_realm=nascent_soul`，
层数依次为 1–9。

## 数值与结算

| 关卡 | 首通 | 重复 |
|:--|:--|:--|
| 云城问舟 | 灵石 100、服务信誉 5 | 灵石 25 |
| 渡口候船 | 灵石 80、服务信誉 5 | 灵石 30 |
| 云舟北渡 | 灵石 120、服务信誉 6 | 灵石 35 |
| 入门问契 | 灵石 100、灵叶 2 | 灵石 30 |
| 契阁残页 | 灵石 70、契约线索 1 | 灵石 35 |
| 遗迹守卫 | 灵石 90、魔核 1 | 灵石 40 |
| 门备材料 | 灵石 80、魔核 1 | 灵石 35 |
| 归舟回城 | 灵石 130、服务信誉 6 | 灵石 35 |
| 回镇结卷 | 灵石 150、护脉片 2、服务信誉 8 | 灵石 45 |

九关均为 `retry.on_incomplete=keep_running`、冷却 0：未达成目标时关卡保持进行中，不扣首通奖励、
不增加尝试次数，`retry.message` 写明该关要重走的具体动作。每关写入自身 `activity_events`
（`story.mainline.xuantian:chapter.N.stage.M`），由既有主线账册展示。

## 消费者

- 移动与云舟：第十章与第十二章的二、三关只依赖既有 `前往`/`结算移动` 与
  `登上云舟`/`结算云舟`；`travel_arrival` 目标除 `travel_sessions` 外也认已抵达的
  `cloud_boat_sessions` 行，云舟航线 `云舟渡口 → 魔渊入口`（60 秒、500 灵石）与返程由此可结算。
- 探索：`explore.demon_abyss`（魔界堕落遗迹探索，元婴 L1，体力 20，日限 2，必战）与
  `explore.demon_threshold`（深渊门备材，元婴 L9，体力 8，日限 6，无战）由既有探索引擎驱动；
  两者均要求 `access.demon_abyss_gate`，该旗标来自既有 `quest.demon_intro`（`接受魔界引导`，筑基一层可做）。
- 奖池：契约线索与魔核分别由 `reward_pool.exploration.demon_abyss`、
  `reward_pool.exploration.demon_threshold` 真实产出，合同测试读取奖池校验目标物品拿得到。
- 敌人：`encounter.demon.fallen_ruins` 的 `enemy.demon_ruins_scout`/`enemy.demon_ruins_warden`
  由既有战斗引擎结算，奖励走出既有 `reward.battle.*` 声明。

## 边界

不新增关卡类型、目标类型、命令、表或字段；不改第九章及以前任何关卡的目标、门槛与奖励；
九关全部 `status=open`、`required_realm=nascent_soul`，未引入跨服、支付或 PvP 内容；
万兽山（`explore.beast_hunt`）留给后续卷，本版不占用其目标。
聚焦证据见 `test/test_yuanying_mainline.py`、`test/test_mainline_nascent_arc.py`。
