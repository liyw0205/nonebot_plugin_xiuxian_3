# 生产域：订单状态机

```text
draft -> submitted -> accepted -> locked -> processing
                                      |          |
                                      +-> rejected/expired
processing -> completed/failed/cancelled -> delivered -> settled
```

个人生产可以从预览进入 locked；委托生产必须双方确认。锁定后材料、精力和报酬不能被其他操作使用。失败按配方返回低品质产物、副产物、部分退款或赔偿。

职业大师作品沿用个人生产状态机。开始时快照道途、辅修、地点、境界、输入、产出、失败返还、质量检定、内容版本和规则版本；结算只读取订单快照。作品配方不能进入委托流程。`recipe.masterwork.support` 在失败时完整返还已生产的三类辅修作品，失败不产生最终支持作品。
