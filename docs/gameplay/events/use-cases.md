# 活动域：用例与验收

## 用例

`activate_task`、`record_task_event`、`claim_task_reward`、`open_event_round`、`record_contribution`、`settle_event_round`、`freeze_ranking`、`claim_ranking_reward`。

## 错误码

`TASK_NOT_FOUND`、`TASK_NOT_ACTIVE`、`TASK_PREREQUISITE_MISSING`、`TASK_WINDOW_CLOSED`、`TASK_ALREADY_CLAIMED`、`EVENT_DUPLICATE`、`EVENT_NOT_OPEN`、`ROUND_ALREADY_SETTLED`。

## 验收

重复事件只推进一次；活动关闭后不能新增进度；奖励重试不重复发放；排行按冻结快照结算；时区和日切由服务端 Clock 决定。