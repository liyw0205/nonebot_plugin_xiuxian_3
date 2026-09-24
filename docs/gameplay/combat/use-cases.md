# 战斗域：用例与验收

## 用例

`start_battle`、`run_turn`（服务端内部）、`resolve_battle`、`claim_battle_reward`、`replay_battle`。

战斗开始后由服务端自动选择合法技能和目标并推进回合。聊天客户端不能提交攻击、防御、
技能、目标、伤害或结算结果；`run_turn` 只供内部 worker/application 调用，并记录自动
策略版本、随机池和 operation ID。

具名遭遇必须在敌人定义的 `location_key` 开始；战斗快照冻结该地点。境界、地点或已有
行动锁任一前置不满足时，不创建会话，也不能生成任务资格证据。

## 错误码

`BATTLE_NOT_FOUND`、`BATTLE_BUSY`、`SKILL_NOT_AVAILABLE`、`TARGET_INVALID`、`RESOURCE_INSUFFICIENT`、`BATTLE_EXPIRED`、`BATTLE_ALREADY_SETTLED`。

## 验收

客户端伪造伤害/技能/目标被拒绝；自动行动重试不重复扣资源；超时和断线释放角色锁；
PvP 结果使用所有参与者的开始快照并可回放；奖励领取不重复生成资产。
