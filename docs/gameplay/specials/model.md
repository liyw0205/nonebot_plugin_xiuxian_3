# 特色玩法域：共享模型

`IdleAssignment`：分配 ID、玩家、路线键、开始/可领取/最大结算时间、已锁槽位、收益快照、状态、operation ID、内容/规则版本。

`DispatchMission`：任务 ID、玩家、任务键、队伍快照（可为单人）、物品/体力锁定、开始/结束时间、风险池、结果、状态与 operation ID。

`CodexEntry`：玩家、条目键、首见来源类型/ID、首次发现时间、内容版本、可见状态、备注摘要。条目只增不改；错误来源进入审计而非覆盖首见记录。

`TowerRun`：挑战 ID、玩家、塔键、楼层、战斗快照、进入成本、次数窗口、状态、结果、首通奖励状态与 operation ID。

`ArenaSnapshot`：快照 ID、玩家、构筑/装备/技能/数值快照、创建时间、有效期、公开状态、版本和防御结果摘要。

`ArenaMatch`：对局 ID、赛季/轮次、挑战者与防守快照、匹配规则、战斗日志、积分变化、奖励状态和 operation ID。

`StoryRun`：运行 ID、玩家、故事键、章节/节点键、已锁选择、条件快照、旗标集合、状态、结局键、版本和 operation ID。

`StoryFlag`：玩家、旗标键、故事运行、首次设置 operation、是否不可逆、内容版本。旗标不能通过普通重试删除或覆盖。

所有模型必须保存 `content_version`、`rule_version`、创建/结算时间和来源 operation；奖励使用独立且可重放的领取 operation。