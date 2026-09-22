# v0.1 资源与物品内容基线

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.1`，`rule_version=items-0.1.0`。背包默认 20 格；堆叠物品每格最多 99，唯一装备/工具每实例占 1 格。物品获得、消耗、装备、耐久和绑定都必须和 operation 同事务。

## 1. 新手资源

寻仙问道成功由 `player.start_seeking` 发放：灵石 100、体力 30/30、精力 30/30、粗糙灵米 3、止血草 3。入道成功由 `player.enter_cultivation` 发放：灵石 200、基础功法 1、对应道途试用技能引用。`new_user` 不拥有钱包、资源或物品；任务奖励是独立 operation，不能合并双发。

## 2. 物品定义

| `item_key` | 类型/堆叠 | 绑定与交易 | 效果/限制 | 主要来源 |
|:--|:--|:--|:--|:--|
| `item.food.coarse_spirit_rice` | 食物，99 | 可交易 | 恢复 3 体力或 3 精力，10 分钟冷却 | 寻仙、任务、烹饪 |
| `item.herb.blood_grass` | 药材，99 | 可交易 | 疗伤丹材料；不可直接换修为 | 寻仙、近郊采集 |
| `item.herb.spirit_leaf` | 药材，99 | 可交易 | 聚气/修炼丹材料 | 灵泉谷、采集 |
| `item.ore.ironstone` | 矿材，99 | 可交易 | 炼器/筑基材料 | 近郊采集 |
| `item.mat.wood` | 木材，99 | 可交易 | 木纹剑、机关基础材料 | 近郊采集 |
| `item.mat.array_sand` | 阵材，99 | 可交易 | 基础阵法/筑基材料 | 引导、采集 |
| `item.food.spirit_rice` | 食物，99 | 可交易 | 恢复 5 体力或 5 精力，10 分钟冷却 | `recipe.food.spirit_rice` |
| `item.array.gathering_basic` | 阵法实例，唯一 | 绑定 24 小时 | 绑定生产设施订单时间 -1000 bp；不叠加 | `recipe.array.gathering_basic` |
| `item.pill.healing_low` | 丹药，99 | 可交易 | 恢复当前气血 3000 bp；战斗每场一次 | 炼丹、任务 |
| `item.pill.focus_low` | 丹药，99 | 可交易 | 一次修炼 `state_bp+1000`；持续到该会话结算 | 炼丹 |
| `item.pill.qi_guard` | 突破丹，9 | 绑定 | 聚气失败保护；成功不消耗 | 任务/炼丹 |
| `item.pill.foundation_draft` | 突破丹，9 | 绑定 | 筑基必需材料 | 炼丹/悬赏 |
| `item.pill.foundation_guard` | 突破丹，9 | 绑定 | 筑基失败保护；成功不消耗 | 炼丹/宗门商店 |
| `item.manual.basic_qi` | 功法，唯一 | 绑定 | 感气修炼许可；学习后不消耗 | 入道奖励 |
| `item.tool.basic_furnace` | 工具，唯一 | 绑定，耐久 2000 bp | 炼丹；订单每次 -100 bp | 入道/生产任务 |
| `item.tool.basic_hammer` | 工具，唯一 | 绑定，耐久 2000 bp | 炼器；订单每次 -100 bp | 入道/生产任务 |
| `item.weapon.wood_sword` | 法器，唯一 | 可交易，耐久 10000 bp | 物理伤害 +5；耐久归零效果为 0 | 新手任务 |
| `item.armor.cotton_robe` | 防具，唯一 | 可交易，耐久 10000 bp | 气血 +20 | 新手任务 |
| `item.cave_pass_basic` | 凭证，1 | 绑定 | 雾隐洞天一层一次进入 | 筑基奖励 |
| `item.token.change_path` | 特殊，1 | 绑定 | 筑基后道途切换；首版仅测试/管理员受控 | 不掉落 |
| `item.fragment.dao_name` | 道号碎片，99 | 绑定 | 机缘寻宝的展示进度材料，不直接改变道号 | 机缘寻宝 |
| `item.clue.recipe_basic` | 基础配方线索，99 | 绑定 | 解锁基础配方线索展示，不直接产出成品 | 机缘寻宝 |
| `item.clue.manual_basic` | 基础功法线索，99 | 绑定 | 解锁基础功法线索展示，不直接授予功法 | 机缘寻宝 |
| `item.token.spirit_tree_water` | 灵木水分券，99 | 绑定 | 行卷付费线奖励；仅用于灵木浇灌 | 问道行卷 |

## 3. 通用操作与失败

`inventory.use_item` 要求物品存在、数量/耐久足够、地点/会话允许、冷却满足；成功写消耗和效果快照。预检查失败不扣数量。唯一实例装备/卸下必须校验槽位，不能同时被订单、战斗、交易锁定。物品交易前锁定，取消/过期按经济域释放。

错误：`ITEM_NOT_FOUND`、`ITEM_QUANTITY_INSUFFICIENT`、`ITEM_BOUND`、`ITEM_DURABILITY_ZERO`、`ITEM_COOLDOWN_ACTIVE`、`INVENTORY_CAPACITY_EXCEEDED`、`ITEM_STATE_LOCKED`。关闭 v0.1 时停止新获得，旧实例只读/按原会话结算。验收：重复 operation 不双耗/双得；焦点丹只影响绑定修炼会话；突破保护成功不消耗；耐久为 0 无效果但实例不丢失；超容量不掉落物品。
