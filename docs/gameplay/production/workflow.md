# 生产域：订单状态机

```text
draft -> submitted -> accepted -> locked -> processing
                                      |          |
                                      +-> rejected/expired
processing -> completed/failed/cancelled -> delivered -> settled
```

个人生产可以从预览进入 locked；委托生产必须双方确认。锁定后材料、精力和报酬不能被其他操作使用。失败按配方返回低品质产物、副产物、部分退款或赔偿。