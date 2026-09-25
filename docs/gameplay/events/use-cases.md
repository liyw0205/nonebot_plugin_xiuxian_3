# 活动域：用例与验收

## 用例

`activate_task`、`record_task_event`、`claim_task_reward`、`open_event_round`、`record_contribution`、`settle_event_round`、`freeze_ranking`、`claim_ranking_reward`、`get_final_heaven_season`、`claim_final_heaven_rewards`、`get_three_realms_season`、`claim_three_realms_rewards`、`get_heart_demon_event`。

v0.3 魔界入侵的玩家入口为 `魔界入侵 [轮次]`、`贡献魔界战场 战斗|运输|维修 [来源operation]`
和 `领取魔界入侵奖励 [轮次]`。贡献只能引用服务端已结算来源；省略来源 operation 时，服务端
选择本轮最新未消费的同类来源。运输、个人设施维修和 `开始魔界战` 的已结算战斗是当前玩家可达来源。

公共跨界事件入口为 `妖界贸易事件 [轮次]`、`贡献妖界贸易 贸易|妖血 [来源operation]`、
`领取妖界贸易奖励 <轮次>`，以及 `界隙裂痕 [轮次]`、`贡献界隙裂痕 [来源operation]`、
`领取界隙裂痕奖励 <轮次>`。妖界贸易来源为已结算固定贸易 operation 或绑定妖血消耗；
界隙裂痕来源为角色参与的已结算界隙队伍胜利。所有来源按
`round_id/player_id/source_operation_id` 去重，查询、贡献和领奖事务都会恢复已落库但未刷新的轮次。

## 错误码

`TASK_NOT_FOUND`、`TASK_NOT_ACTIVE`、`TASK_PREREQUISITE_MISSING`、`TASK_WINDOW_CLOSED`、`TASK_ALREADY_CLAIMED`、`EVENT_DUPLICATE`、`EVENT_NOT_OPEN`、`ROUND_ALREADY_SETTLED`、`FINAL_RANKING_NOT_FINALIZED`、`FINAL_RANKING_NOT_ELIGIBLE`、`FINAL_RANKING_REWARD_CLAIMED`、`FINAL_RANKING_CLAIM_EXPIRED`。

魔界入侵补充错误码：`EVENT_CONTRIBUTION_SOURCE_INVALID`、`EVENT_CONTRIBUTION_INSUFFICIENT`、
`EVENT_REWARD_ALREADY_CLAIMED`、`EVENT_REWARD_EXPIRED` 和 `OPERATION_CONFLICT`。
公共跨界事件复用上述来源、贡献和领奖错误码。
心魔事件入口为 `心魔事件 [事件编号]`；超时按 `heart_demon.face` 自动结算且不进入公共排行。补充错误码：`HEART_DEMON_ALREADY_RESOLVED`、`HEART_DEMON_NOT_FOUND`。

三界赛季补充错误码：`THREE_REALMS_RANKING_NOT_FINALIZED`、`THREE_REALMS_REWARD_NOT_ELIGIBLE`、
`THREE_REALMS_REWARD_ALREADY_CLAIMED`、`THREE_REALMS_REWARD_EXPIRED` 和 `OPERATION_CONFLICT`。

## 验收

重复事件只推进一次；活动关闭后不能新增进度；奖励重试不重复发放；排行按冻结快照结算；时区和日切由服务端 Clock 决定。心魔事件投影与突破失败同事务写入，已结算事件不能再次选择。

终局赛季读取 `endgame_endings` 和已结算 `final_battle_sessions/members`，不接受命令参数提交积分。
只有飞升或留界的不可逆结局可以进入对应结局榜；协作榜只累计至少两人且成功结算的终局战，
并按成员累计。赛季窗口闭合后首次查询/领奖会以单事务冻结三个榜，重放读取同一快照。
公开 DTO 只含匿名别名、名次、积分和达成时间。前十领奖称号，榜首领奖时额外确认
`chapter.final_heaven`；重复 operation 回放，另一个 operation 重复领取返回
`FINAL_RANKING_REWARD_CLAIMED`。超过 7 天窗口后只自动补发展示称号，不自动发放或确认篇章资格。

三界赛季按 28 日 UTC 窗口冻结三榜；阵营榜只读取已结算公共事件贡献流水，多人榜读取已结算多人战斗的服务端贡献快照，宗门榜读取窗口内有效宗门贡献。冻结后数据变化不重算，历史赛季重复查询不重复插入排名；公开 DTO 不含平台用户 ID、道号或内部角色 ID。
