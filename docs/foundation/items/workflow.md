# 物品域：生命周期

```text
defined -> granted -> owned -> equipped/locked
owned/equipped -> consumed/destroyed/transferred
locked -> settled/unlocked
```

交易、生产、战斗奖励先锁定或待领取，再由唯一结算 operation 转为持有。

背包容量、绑定、堆叠、耐久和唯一性必须在同一事务检查。定义下线不影响已有实例读取和历史结算。