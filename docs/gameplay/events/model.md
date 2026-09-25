# 活动域：任务与轮次模型

`TaskDefinition`：任务键、版本、类型、前置、目标、计数事件、窗口、奖励、失败和可见范围。

`PlayerTask`：玩家、任务键/版本、窗口键、进度、状态、领取状态和 operation ID。

`EventRound`：事件键、轮次、时间、阶段、参与条件、贡献规则、奖励池、结算状态和版本。
`HeartDemonEventProjection`：个人事件键、突破会话/结算 operation、状态、选择、截止时间、失败快照和结算结果；不参与公共排行。

`FinalHeavenSeason`：赛季 ID、UTC 起止时间、规则版本、收集/冻结状态、匿名快照与领奖截止时间。
`FinalHeavenRanking`：赛季、榜单键、内部玩家外键、名次、积分、达成时间、匿名别名和展示奖励状态。
身份外键只用于个人领奖查询，不得出现在公开快照或 application DTO。

`ThreeRealmsSeason`：28 日 UTC 赛季 ID、起止时间、规则版本、收集/冻结状态、匿名快照与 7 日领奖截止时间。
`ThreeRealmsRanking`：赛季、阵营功勋/多人副本贡献/宗门贡献榜键、内部玩家外键、名次、积分、达成时间、匿名别名和领奖状态。
`ThreeRealmsClaim`：赛季、角色、领奖 operation、叠加奖励和领取时间；绑定神魂晶另写入赛季绑定审计表。
公开 DTO 只返回匿名别名、名次、积分和达成时间，身份外键不得泄露。

`DomainFrontRound`：4 小时活动窗口中的 30 分钟轮次、地点、目标、状态、冻结结果和领奖截止时间。
`DomainFrontParticipant`：轮次、角色、宗门、领域、参战快照、体力成本和个人贡献；每宗门每轮最多 20 人。
`DomainFrontContribution`：来源 operation、战斗/占点动作、数量、角色/宗门/领域归属和贡献 operation；
来源按轮次/角色/operation 唯一。`DomainWarSeason` 与 `DomainWarRanking` 保存 21 日 UTC 赛季、
匿名冻结榜和 7 日领奖窗口。
`DomainCoreRedemption`：赛季、角色、兑换 operation 和兑换时间；每角色每赛季唯一，消耗 20 个绑定领域核心碎片并发放 1 个领域核心。

`VoidArchiveRun`：角色、UTC 周次、已结算档案航道、`enemy.archive_keeper` 战斗、结果、奖励快照和 operation；
同一航道只能结算一次，周内首个胜利发放 `item.void_archive`，后续胜利转换为 `item.void_crystal` ×3。
`VoidArchiveTask`：角色、周次、`task.archive_fragment.alpha|beta|gamma`、服务端证据进度、奖励和领取 operation；
三项均领取后写入唯一 `event.archive_unlock` 窗口，任务不接受客户端提交进度。

排行使用冻结快照；活动结束后的奖励进入待领取、自动补发或过期状态。终局赛季和三界赛季均有独立的
season repository，不与灵泉轮次仓储混放。
