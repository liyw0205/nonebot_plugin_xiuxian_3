# 世界域：移动状态机

```text
travel: created -> running -> arrived
                    \-> interrupted/expired/failed
location: locked -> open -> closed
```

v0.2 云舟使用独立 `cloud_boat_sessions` 会话，状态为 `created/running/arrived/failed/expired`。
云舟航线在创建时冻结来源、终点、费用、凭证、`content_version` 和 `rule_version`；洞天二层和
深渊门不能通过普通 `travel_sessions` 直达。已运行航线到期后由结算/恢复按快照抵达，不随机
失事，不重复扣费。魔界引导和阵堂权限是独立 operation，失败不泄露生产结果。

创建移动前检查地点、入口条件、角色战斗/生产/突破锁和资源。创建后先锁定费用，抵达结算才写入新位置和途中事件。

普通地点的通行物品在会话创建时扣除；飞升路的 `item.ascension_certificate` 在创建时只校验、
不扣除，抵达结算时与位置更新在同一事务内扣除。抵达时凭证不足必须整笔回滚，保留
`running` 状态和原位置；成功结算写入 `arrived`，重复 operation 只回放原结果。

地点关闭不强制删除已在其中的角色；后续行动按撤离或封锁规则处理。重复到达结算只能写一次位置变更。
