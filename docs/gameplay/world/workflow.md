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

妖界史阅读单独记录任务事件；完成妖界引导在一个事务中校验筑基、本人阅读事件、本人已结算的近郊探索和灵石，再写入入口权限、声望、任务事件与进度。万兽山预览和移动事务共用声望 `>=200` 或引导权限的准入规则，元婴门槛保持不变。

v0.5 虚空航道使用独立 `void_route_sessions` 会话。`结算虚空航道` 在发放航道奖励的同一事务
把 `players.location_key` 更新为航道键（例如 `void.archive_ruins`），并将抵达位置写入
operation 结果；重复结算只回放原结果。下游地点准入因此只能消费真实航道抵达证据，不能依赖
手工改写角色位置。

创建移动前检查地点、入口条件、角色战斗/生产/突破锁和资源。创建后先锁定费用，抵达结算才写入新位置和途中事件。

跨界地点的阵营声望在预览阶段展示缺口，并在开始事务内重新读取并原子校验；不足时不得扣除体力或灵石。
开始成功后，移动会话快照必须保存阵营、所需声望、开始时声望值、`content_version` 和 `rule_version`，
后续结算不得因规则或角色声望变化改写已开始的准入结果。

普通地点的通行物品在会话创建时扣除；飞升路的 `item.ascension_certificate` 在创建时只校验、
不扣除，抵达结算时与位置更新在同一事务内扣除。抵达时凭证不足必须整笔回滚，保留
`running` 状态和原位置；成功结算写入 `arrived`，重复 operation 只回放原结果。

地点关闭不强制删除已在其中的角色；后续行动按撤离或封锁规则处理。重复到达结算只能写一次位置变更。
