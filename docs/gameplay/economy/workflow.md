# 经济域：交易状态机

```text
created -> accepted -> locked -> processing -> delivered -> settled
   |          |          |          |
cancelled  rejected   expired    failed
```

购买顺序：锁定买方灵石 -> 确认卖方物品 -> 扣手续费 -> 转移物品 -> 结算卖方余额 -> 写终态。

终态不能重新打开。过期清理必须解锁资产或退款，清理 operation 可重试。

固定跨界贸易使用独立的 `cross_realm_trades` 事务：先校验地点、对应阵营声望、周计数、输入和灵石；三界贸易口还要同时校验魔界与妖界声望，
再同事务扣除输入并写入输出绑定。成功快照保存 `content-0.3`、`economy-0.3.0`、周起始日和准入值；
同一 operation 只回放原结果，任何校验失败不扣资源。

限量拍卖状态为 `open -> settled|unsold|expired`。发布时锁卖方物品但不重复扣背包；竞价时扣并锁当前最高出价，
被超越立即退款；结束后 10 分钟内由结算 operation 原子转移物品/灵石，超过窗口则退款并流拍。周槽位和所有锁定
都在 `BEGIN IMMEDIATE` 事务内校验，重试只回放原拍卖结果。
