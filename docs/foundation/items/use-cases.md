# 物品域：用例、错误与验收

## 用例

- `grant_item`：发放固定或随机物品。
- `consume_item`：消耗指定数量。
- `equip_item` / `unequip_item`：修改装备槽并生成属性快照。
- `use_item`：应用物品效果并扣除物品。
- `repair_item`：消耗材料恢复耐久。
- `claim_reward`：从待领取奖励包结算资产。

## 错误码

`ITEM_DEF_NOT_FOUND`、`INVENTORY_FULL`、`ITEM_NOT_OWNED`、`ITEM_BOUND`、`EQUIP_SLOT_BUSY`、`REQUIREMENT_MISSING`、`ITEM_COOLDOWN`、`ITEM_TARGET_INVALID`、`DURABILITY_FULL`、`RESOURCE_INSUFFICIENT`、`ITEM_OPERATION_CONFLICT`。

## 验收

容量不足时奖励进入待领取或整体拒绝；使用重试只扣一次；绑定物品不能非法转移；随机奖励保存池版本和实际结果；失败事务不产生部分资产。