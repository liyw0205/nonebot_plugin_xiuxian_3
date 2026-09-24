# 活动域：用例与验收

## 用例

`activate_task`、`record_task_event`、`claim_task_reward`、`open_event_round`、`record_contribution`、`settle_event_round`、`freeze_ranking`、`claim_ranking_reward`、`get_final_heaven_season`、`claim_final_heaven_rewards`。

## 错误码

`TASK_NOT_FOUND`、`TASK_NOT_ACTIVE`、`TASK_PREREQUISITE_MISSING`、`TASK_WINDOW_CLOSED`、`TASK_ALREADY_CLAIMED`、`EVENT_DUPLICATE`、`EVENT_NOT_OPEN`、`ROUND_ALREADY_SETTLED`、`FINAL_RANKING_NOT_FINALIZED`、`FINAL_RANKING_NOT_ELIGIBLE`、`FINAL_RANKING_REWARD_CLAIMED`、`FINAL_RANKING_CLAIM_EXPIRED`。

## 验收

重复事件只推进一次；活动关闭后不能新增进度；奖励重试不重复发放；排行按冻结快照结算；时区和日切由服务端 Clock 决定。

终局赛季读取 `endgame_endings` 和已结算 `final_battle_sessions/members`，不接受命令参数提交积分。
只有飞升或留界的不可逆结局可以进入对应结局榜；协作榜只累计至少两人且成功结算的终局战，
并按成员累计。赛季窗口闭合后首次查询/领奖会以单事务冻结三个榜，重放读取同一快照。
公开 DTO 只含匿名别名、名次、积分和达成时间。前十领奖称号，榜首领奖时额外确认
`chapter.final_heaven`；重复 operation 回放，另一个 operation 重复领取返回
`FINAL_RANKING_REWARD_CLAIMED`。超过 7 天窗口后只自动补发展示称号，不自动发放或确认篇章资格。
