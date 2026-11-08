# v0.11 冒险内容基线（玄天卷第九章「云城旧账」）

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.11`。

主线在 `chapter.8.stage.3` 之后原本直接终止（`next_stage_key` 为空），尽管该关正文只写完
近郊一卷。本版补上第九章三关，把玄天卷接到云城与雾隐洞天的旧账上。

## 第九章关卡

| 关卡 | 名称 | 目标 | 门槛 |
|:--|:--|:--|:--|
| `chapter.9.stage.1` | 云城受讬 | 抵达 `xuantian.cloud_city` | 金丹 L1 |
| `chapter.9.stage.2` | 街巷护送 | 在 `explore.cloud_city_escort` 赢得一场遭遇战 | 金丹 L2 |
| `chapter.9.stage.3` | 雾中旧账 | 在 `explore.mist_grotto` 结算中取得灵叶×1 | 金丹 L3 |

链路：`chapter.8.stage.3` → `chapter.9.stage.1` → `chapter.9.stage.2` → `chapter.9.stage.3`（终点）。

## 数值与结算

| 关卡 | 首通 | 重复 |
|:--|:--|:--|
| 云城受讬 | 灵石 70、服务信誉 5 | 灵石 20 |
| 街巷护送 | 灵石 80、灵叶 2、服务信誉 5 | 灵石 25 |
| 雾中旧账 | 灵石 90、服务信誉 6 | 灵石 30 |

三关均为 `retry.on_incomplete=keep_running`、冷却 0：未达成目标时不扣首通奖励，也不增加尝试次数。
每关写入自身 `activity_events`（`story.mainline.xuantian:chapter.9.stage.N`），由既有主线账册展示。

## 消费者

- `explore.cloud_city_escort`（云城护送，筑基 L1，体力 7，日限 5，战斗 2500 bp）与
  `explore.mist_grotto` 均由既有探索引擎驱动；第二章街巷护送目标额外要求该模式确实配置了遭遇战
  （`battle_chance_bp > 0`）。
- 雾中旧账要求的 `item.herb.spirit_leaf` 由 `reward_pool.exploration.mist_grotto` 真实产出，
  合同测试直接读取该奖池校验，避免目标指向拿不到的物品。
- 本章两场战斗的敌人 `enemy.mist_guardian` 等的奖励由 `reward.battle.*` 声明表结算（见
  [战斗内容 v0.9](../combat/content-v0.9.md)），首通与实际到手的产出一致。

## 边界

不新增关卡类型、目标类型、命令或表；不改第八章及以前任何关卡的目标、门槛与奖励；三关全部为
`status=open` 且 `required_realm=golden_core`，未引入跨服/支付/PvP 内容。
聚焦证据见 `test/test_mainline_chapter_nine.py`。
