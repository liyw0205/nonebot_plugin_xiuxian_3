# 探索域：结算状态机

```text
exploration: created -> running -> waiting -> completed -> settled
                                  \-> cancelled/expired/failed
bounty: generated -> viewed -> accepted -> progress -> completed -> settled
                                             \-> expired/cancelled/failed
```

开始时锁定费用/次数；结算时读取服务端快照。取消只退未使用资源；失败按风险规则产生低级资源、虚弱、线索或救援。终态不能重复结算。