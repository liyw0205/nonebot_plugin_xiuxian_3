# 物品域：用例、错误与验收

## 用例

- `grant_item`：发放固定或随机物品。
- `consume_item`：消耗指定数量。
- `equip_item` / `unequip_item`：修改法器、防具或饰品的独立装备槽，并记录穿脱流水；同槽已有装备、耐久耗尽或准入不足时整体拒绝。
- `use_item`：应用物品效果并扣除物品。
- `repair_item`：消耗材料恢复耐久。
- `claim_reward`：从待领取奖励包结算资产。

## 错误码

`ITEM_DEF_NOT_FOUND`、`INVENTORY_FULL`、`ITEM_NOT_OWNED`、`ITEM_BOUND`、`EQUIP_SLOT_BUSY`、`REQUIREMENT_MISSING`、`ITEM_COOLDOWN`、`ITEM_TARGET_INVALID`、`DURABILITY_FULL`、`RESOURCE_INSUFFICIENT`、`ITEM_OPERATION_CONFLICT`。

## 验收

容量不足时奖励进入待领取或整体拒绝；使用重试只扣一次；绑定物品不能非法转移；随机奖励保存实际结果；失败事务不产生部分资产。物品名称、别名、绑定和交易属性只从当前 `item` 内容记录读取，不能在市场或使用入口重复维护。待消费效果保存类型、数值、来源 operation 和消费时间，消费时冻结并清空；灵食按内容声明择一恢复体力或精力，实际恢复量受上限约束，冷却、背包扣除和 operation 同事务落盘；冷却跨重启保留，故障回滚后原操作可重试；坏快照整体拒绝。装备穿戴、卸下和查看须覆盖 QQ 官方与 OneBot V11 两条适配器路径：同一 operation 重放只返回原结果，输入冲突不改变资产或槽位，重启后仍可恢复；正式 PvE/PvP 只消费开战时已穿戴实例，切磋和训练傀儡不得创建装备流水或改变装备状态。
