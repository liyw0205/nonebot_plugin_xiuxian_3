# 探索域：结算状态机

```text
exploration: created -> settled
                     \-> cancelled/expired
                     \-> combat_pending -> settled
bounty: generated -> viewed -> accepted -> progress -> completed -> settled
                                             \-> expired/cancelled/failed
```

开始时锁定费用/次数；结算时读取服务端快照。取消只允许在 `created` 阶段并返还本次
体力；失败按风险规则产生低级资源、虚弱、线索或救援。遭遇结算先固定 roll 和基础奖励，
再创建关联自动回合战斗。战斗胜利才发放冻结奖励，失败发放空奖励；战斗行动和探索结算
均由 operation ledger 幂等保护。历史 `combat_pending` 会话可在重启后继续创建/回放战斗，
终态不能重复结算。
