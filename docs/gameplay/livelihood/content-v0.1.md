# v0.1 常驻经营内容基线：城镇生计、居所与灵田

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.1`，`rule_version=livelihood-0.1.0`。所有 `mortal`、`seeker` 与 `cultivator` 均可参与；境界层数不是基础准入。**常驻经营的结算禁止写入 `realm_cultivation`、`total_cultivation`、突破准备度、伤害或突破概率。**

## 1. 居所与休整

| `residence_key` | 前置/成本 | 效果 | 配额与失败 |
|:--|:--|:--|:--|
| `residence.town_room` | `mortal` 以上；租金 20 灵石/3 业务日 | 开放 1 个休整位、1 个私人物资箱（10 格） | 逾期进入 `overdue`，不可开启新休整/地块，已有订单继续结算 |
| `residence.courtyard` | 地方名望 `xuantian.new_town>=40`；租金 80 灵石/7 日 | 休整位 2、地块 1、物资箱 20 格 | 同角色仅一处 active；搬迁必须无地块/路线/服务锁 |

`livelihood.rest` 在 active 居所执行：30 分钟，消耗 0，恢复体力 8 与精力 8；每日最多 2 次，不能在战斗/移动/突破/生产中开始。重复 operation 回放同一恢复结果；资源已满时返回 `REST_NOT_NEEDED`，不占次数。休整不是修炼，不增加任何修为。

## 2. 灵田与基础种植

| `crop_key` | 前置/输入 | 生长/维护 | 收获 | 失败/上限 |
|:--|:--|:--|:--|:--|
| `crop.blood_grass` | active 居所地块；`item.herb.blood_grass` 1 作种 | 4h；精力 1；生长期间至少维护 1 次（精力 1） | `item.herb.blood_grass` 3、地方名望 +1 | 未维护：产量 1；每地块/业务日最多 2 轮 |
| `crop.spirit_leaf` | `residence.courtyard`；`item.herb.spirit_leaf` 1 作种 | 8h；精力 2；维护 2 次 | `item.herb.spirit_leaf` 3、`item.mat.array_sand` 0–1（`livelihood.harvest.v0.1`） | 未维护：仅灵叶 1；每地块/业务日最多 1 轮 |

播种在 `livelihood.plant` 成功时锁种子/精力并固定 `harvest_at`、作物、维护阈值与随机池。维护仅在 `growing` 状态可做；收获只在 `harvestable` 状态可做。产量随机只用于灵叶副产物，保存实际抽取；不能通过重试重抽。地块不可同时播种；过期 24h 未收获进入 `withered`，种子/精力不返，清理后可重新种植。

## 3. 城镇委托与地方名望

`town.new_town.<business_date>` 每日生成下列三个固定委托，角色最多接受 2 个，所有委托不要求修行境界：

| `commission_key` | 交付/行为 | 报酬 | 地方名望/信誉 | 库存/期限 |
|:--|:--|:--|:--|:--|
| `town_commission.herb_supply` | `item.herb.blood_grass` 3 | 灵石 18 | `local.xuantian.new_town +3`、服务信誉 +1 | 全服 200 单；12h |
| `town_commission.repair_tools` | `item.mat.wood` 2、`item.ore.ironstone` 1 | 灵石 25 | 名望 +4、信誉 +1 | 全服 120 单；12h |
| `town_commission.meal_service` | `item.food.spirit_rice` 2 | 灵石 20 | 名望 +3、信誉 +1 | 全服 150 单；12h |

接受时仅锁定委托名额，不锁物品；交付时检查物品、原子扣库存/物品并发放报酬。库存耗尽、过期、暂停或重复交付均不扣物。`local.xuantian.new_town` 上限 1000；服务信誉上限 100。达到名望 40 开 `residence.courtyard`，名望 100 开城市委托第二槽，信誉 10 开普通服务订单承接资格；不得影响战斗、修炼或突破。

## 4. 服务订单与短途运输

| `service_key` | 前置/成本 | 结果 | 配额/风险 |
|:--|:--|:--|:--|
| `service.gather_help` | 信誉 >=10；同地点；体力 3 | 为委托人完成 1 次教学采集，承接者获灵石 15 | 每日 3；采集失败仅退 1 体力，不收服务报酬 |
| `service.cook_meal` | 烹饪教学、精力 2、灵米 2 | 交付灵米饭 2；承接者获锁定报酬 | 每日 5；沿用生产质量/失败快照 |
| `route.new_town_outskirts` | `mortal` 以上；货物价值 <=100 灵石；体力 2 | 10 分钟后固定报酬 12 灵石、名望 +2 | 每日 3；`route.town.v0.1` 10% 延误，延误仅多 10 分钟不丢货 |

服务订单状态和报酬锁定按 `LivelihoodOrder`。发布人可在 `published` 取消并全额解锁；承接后材料/报酬/精力进入锁定，成功交付支付承接者 9800 bp，平台回收 200 bp；失败或 24h 超时按快照退未消耗材料和 8000 bp 报酬，承接者信誉不变。运输在 `in_transit` 不可取消；延误不扣货，路线失败只发生在服务端恢复异常并全额解锁货物/不支付报酬。

## 5. 经营记录、关闭与验收

每次写操作记录居所/地块/委托/订单/路线 ID、业务日、库存、输入输出、名望/信誉前后值、随机池/结果、内容版本与 operation。关闭 v0.1 时停止新租赁、播种、委托和路线；已有地块可收获，已锁订单/路线按原快照结算或原路释放。

验收：凡人能完成所有表中动作；任何经营结算的两类修为字段均不变；委托库存与地块锁并发唯一；过期不双返；地方名望/信誉不能兑换突破材料或作为突破加成。