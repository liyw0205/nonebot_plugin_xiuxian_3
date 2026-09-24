# 探索域：会话模型

`ExplorationSession`：`exploration_id`、角色/队伍、地点、模式、风险、路线阶段、费用快照、随机池版本、状态和结果摘要。
开始时还冻结 `realm_key`/`realm_layer`、资质、道途、基础气血/先手、装备快照、遭遇概率、
规则版本和随机种子。遭遇创建后在结果摘要中保存 `battle_id`、敌人键和 `battle_outcome`，
以便重启恢复与幂等回放；探索奖励先保存为 `frozen_result`，只在战斗胜利时写入玩家资产。

`GatheringNode`：节点键、地点、资源池、库存、刷新时间、玩家次数、保护状态和内容版本。

`BountyOffer`：offer 键、轮次、目标、期限、风险、奖励池、声望、接取状态和版本。生成后目标与奖励固定。

探索会话状态中的 `combat_pending` 只表示遭遇战尚未完成，不是可直接领奖的终态；最终结果
必须关联已 `settled` 的 `BattleSession`。
