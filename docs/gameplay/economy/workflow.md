# 经济域：交易状态机

```text
created -> accepted -> locked -> processing -> delivered -> settled
   |          |          |          |
cancelled  rejected   expired    failed
```

购买顺序：锁定买方灵石 -> 确认卖方物品 -> 扣手续费 -> 转移物品 -> 结算卖方余额 -> 写终态。

终态不能重新打开。过期清理必须解锁资产或退款，清理 operation 可重试。