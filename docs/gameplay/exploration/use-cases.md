# 探索域：用例与验收

## 用例

`start_exploration`、`resolve_exploration`、`cancel_exploration`、`refresh_bounty`、`accept_bounty`、`settle_bounty`、`enter_instance`、`settle_instance`。

## 错误码

`EXPLORATION_BUSY`、`EXPLORATION_EXPIRED`、`EXPLORATION_NOT_SETTLEABLE`、`OFFER_NOT_FOUND`、`DAILY_LIMIT_REACHED`、`RISK_REQUIREMENT_MISSING`、`NODE_EMPTY`、`INSTANCE_ALREADY_SETTLED`。

## 验收

重复 start 不重复扣体力；采集并发只有一个请求扣库存；悬赏刷新不修改已接 offer；取消不退已发生损耗；秘境奖励领取重试不重复发放。