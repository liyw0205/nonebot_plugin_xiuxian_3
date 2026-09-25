# v0.2 生产内容基线：金丹配方与洞天二层设施

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.2`，`rule_version=production-0.2.0`。金丹生产质量阈值提高到 6000；失败返还每类可返材料 60%，工具额外 -150 bp 耐久。

| `recipe_key` | 前置/地点 | 输入 | 工具/精力/时长 | 成功产出 | 限制 |
|:--|:--|:--|:--|:--|:--|
| `recipe.pill.golden_core_guard` | `alchemy` 3、金丹、炼丹房 | 灵叶 3、`item.material.cloud_iron` 1、血草 2 | 炉，8 精力，120 秒 | `item.pill.golden_core_guard` 1 | 每日 4；质量 <6000 失败 |
| `recipe.pill.core_condense` | `alchemy` 4、金丹 | 灵叶 5、云铁 2、洞天材料 2 | 炉，10 精力，180 秒 | `item.pill.core_condense` 1 | 每日 2；绑定 |
| `recipe.weapon.cloud_sword` | `artifice` 3、金丹、炼器台 | 云铁 4、阵砂 1、木材 2 | 锤，10 精力，180 秒 | `item.weapon.cloud_sword` 1 | 每日 2；耐久 `8500+quality/10` |
| `recipe.array.mist_barrier` | `formation` 3、阵堂/洞天二层 | 阵砂 5、灵石 100、灵叶 2 | 12 精力，240 秒 | `item.array.mist_barrier` 1 | 每日 2；绑定洞天二层 12 小时；过期 job 幂等标记 `expired` |
| `recipe.food.cloud_tea` | 烹饪 2、灵泉谷 | 灵叶 2、粗糙灵米 2 | 4 精力，60 秒 | `item.food.cloud_tea` 3 | 每日 6；修炼会话 +500 bp |

当前运行时已开放表中五条配方的个人预览、生产和结算，洞天设施槽位与维护费也已开放。成品使用入口为 `使用 云灵茶` 和 `使用 迷雾屏障阵 雾隐洞天二层`：云灵茶消费一份并在下一次修炼开始时冻结 `state_bp +500`，同一待用效果不可重复消费；迷雾屏障阵消费一份、在洞天二层绑定 12 小时并将该地点探索风险降低 500 bp，同地点同类阵法不叠加。云纹剑生产成功后直接创建 `equipment_instances`，耐久按 `8500+quality/10`（上限 10000）冻结，同时保留旧 `durability_json` 投影。`formation 3`、`alchemy 3/4`、`artifice 3` 和 `cooking 2` 在订单质量快照中分别冻结为基础熟练度 `4000/4000/5000/4000 bp`，质量仍按 v0.1 公式和服务端随机池计算；金丹配方和云剑使用 6000 成功阈值，云茶使用 4500 成功阈值。

## 洞天二层设施

`cave.mist_grotto_2` 开放 4 块灵田、炼丹房、炼器台、阵基各 1 个基础槽。宗门/个人必须通过 `production.claim_facility_slot` 锁定槽位：每槽 1 个 running 订单；维护费每业务日 100 灵石由所有者支付，余额不足时设施 `inactive`，不取消已 processing 订单。`item.array.gathering_basic` 使绑定设施订单时长 -1000 bp；同类阵法不叠加。

错误：`FACILITY_SLOT_REQUIRED`、`FACILITY_SLOT_OCCUPIED`、`FACILITY_MAINTENANCE_UNPAID`、`FACILITY_OWNER_INVALID`、`RECIPE_QUALITY_INSUFFICIENT`、`GOLDEN_CORE_REQUIREMENT_MISSING`。关闭后新订单停止，已锁材料按原版本结算。验收：维护 job 幂等；槽位并发唯一；阵法不叠加；失败材料/耐久准确；绑定突破丹不可市场出售。
