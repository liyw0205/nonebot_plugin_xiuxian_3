# 活动域：任务与轮次模型

`TaskDefinition`：任务键、版本、类型、前置、目标、计数事件、窗口、奖励、失败和可见范围。

`PlayerTask`：玩家、任务键/版本、窗口键、进度、状态、领取状态和 operation ID。

`EventRound`：事件键、轮次、时间、阶段、参与条件、贡献规则、奖励池、结算状态和版本。
`HeartDemonEventProjection`：个人事件键、突破会话/结算 operation、状态、选择、截止时间、失败快照和结算结果；不参与公共排行。

`FinalHeavenSeason`：赛季 ID、UTC 起止时间、规则版本、收集/冻结状态、匿名快照与领奖截止时间。
`FinalHeavenRanking`：赛季、榜单键、内部玩家外键、名次、积分、达成时间、匿名别名和展示奖励状态。
身份外键只用于个人领奖查询，不得出现在公开快照或 application DTO。

排行使用冻结快照；活动结束后的奖励进入待领取、自动补发或过期状态。终局赛季有独立的
`season_repository.py`，不与灵泉轮次仓储混放。
