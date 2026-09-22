# 探索域：结算状态机

```text
exploration: created -> settled
                     \-> cancelled/expired/combat_pending
bounty: generated -> viewed -> accepted -> progress -> completed -> settled
                                             \-> expired/cancelled/failed
```

开始时锁定费用/次数；结算时读取服务端快照。取消只允许在 `created` 阶段并返还本次
体力；失败按风险规则产生低级资源、虚弱、线索或救援。`combat_pending` 是等待后置战斗
运行时的锁定状态，重复结算只回放挂起结果，不重复抽取探索奖励。终态不能重复结算。
