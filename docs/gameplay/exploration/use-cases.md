# 探索域：用例与验收

## 用例

`start_exploration`、`resolve_exploration`、`cancel_exploration`、`refresh_bounty`、`accept_bounty`、`settle_bounty`、`enter_instance`、`settle_instance`。
`resolve_exploration` 遇到遭遇时由服务端调用 `start_exploration_battle`、自动推进回合并
调用 `settle_exploration_combat`；客户端没有战斗行动入口。

## 错误码

`EXPLORATION_BUSY`、`EXPLORATION_EXPIRED`、`EXPLORATION_NOT_SETTLEABLE`、`EXPLORATION_COMBAT_PENDING`、`EXPLORATION_COMBAT_NOT_SETTLED`、`OFFER_NOT_FOUND`、`DAILY_LIMIT_REACHED`、`RISK_REQUIREMENT_MISSING`、`NODE_EMPTY`、`INSTANCE_ALREADY_SETTLED`。

## 验收

重复 start 不重复扣体力；采集并发只有一个请求扣库存；悬赏刷新不修改已接 offer；取消不退已发生损耗；秘境奖励领取重试不重复发放。探索遭遇必须验证开始快照与敌人地点/境界，
QQ 官方和 OneBot V11 均能完成遭遇、战斗回放、重启后结算；战斗失败不发冻结奖励，重复结算
不重复写入资产或灵泉贡献。
