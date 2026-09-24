# v0.2 物品内容基线：金丹与玄天中层

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.2`，`rule_version=items-0.2.0`。v0.2 新物品默认需要金丹或对应地点/任务；`dao` 品阶正式开放，`heaven` 以上仍不掉落。

| `item_key` | 类型/堆叠 | 绑定/交易 | 效果、成本与限制 | 来源 |
|:--|:--|:--|:--|:--|
| `item.pill.core_condense` | 突破丹，9 | 绑定 | 金丹突破必需；仅在开始会话时锁定，失败/成功均消耗 | 金丹炼丹、宗门商店 |
| `item.pill.golden_core_guard` | 保护丹，9 | 绑定 | 金丹失败保留 70% 修为、震荡 4 小时；成功不消耗 | 金丹炼丹、宗门商店 |
| `item.pill.golden_core_restore` | 恢复丹，9 | 绑定 | 提前解除 `foundation_shock`；额外灵石 200；每震荡一次 | 金丹配方 |
| `item.material.cloud_iron` | 矿材，99 | 可交易 | 金丹突破/炼器材料 | 云铁矿区、委托 |
| `item.ticket.cloud_boat_fragment` | 票碎片，99 | 绑定，不可交易 | 云舟试炼任务物；按冻结奖励池掉落，不直接抵扣航线费用 | 云舟试炼 |
| `item.weapon.cloud_sword` | 法器，唯一 | 可交易，耐久 10000 bp | 伤害 +35、身法 +5；精英战每场耐久 -150 bp | 云舟秘境 |
| `item.armor.cloud_robe` | 防具，唯一 | 可交易，耐久 10000 bp | 气血 +120、控制抵抗 +500 bp | 云舟秘境 |
| `item.cave_pass_advanced` | 凭证，1 | 绑定 | 雾隐洞天二层单次许可；进入后消耗 | 金丹悬赏 |
| `item.token.faction_seal` | 特殊，1 | 绑定 | 金丹道途分支前置；确认分支时消耗 | 阵营首领/主线 |
| `item.array.mist_barrier` | 阵法实例，唯一 | 绑定 12h | 指定地点风险 -500 bp；同地点同类不叠加 | `recipe.array.mist_barrier` |
| `item.food.cloud_tea` | 食物，99 | 可交易 | 下一次修炼会话 `state_bp +500` | `recipe.food.cloud_tea` |

## 获取、使用和关闭

精英掉落池 `loot.xuantian.elite.v0.2`：云铁 50%、金丹材料 30%、装备 15%、凭证 5%；按战斗奖励 operation 固定实际抽取。装备实例的绑定、耐久、随机词条（本版本无随机词条）与来源写入奖励流水。

`item.cave_pass_advanced` 在进入会话开始时锁定，只有移动/探索会话成功创建后消耗；入口条件失败、容量不足或 operation 冲突时释放锁定。`item.token.faction_seal` 不能交易、拆解或由管理员普通调整发放。

错误：`ITEM_REALM_REQUIREMENT_MISSING`、`ITEM_LOCATION_REQUIREMENT_MISSING`、`ITEM_INSTANCE_LOCKED`、`ITEM_DURABILITY_ZERO`、`INVENTORY_CAPACITY_EXCEEDED`。关闭 v0.2 后停止新掉落/商店出售；已有物品可按原订单、战斗和维修规则处理。验收：随机池回放相同物品；金丹保护丹成功不消耗；凭证失败入口不消耗；耐久与交易锁同事务；道品不提前在 v0.1 掉落。
