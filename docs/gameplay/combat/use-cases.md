# 战斗域：用例与验收

## 用例

`start_battle`、`run_turn`（服务端内部）、`resolve_battle`、`claim_battle_reward`、`replay_battle`。

战斗开始后由服务端自动选择合法技能和目标并推进回合。聊天客户端不能提交攻击、防御、
技能、目标、伤害或结算结果；`run_turn` 只供内部 worker/application 调用，并记录自动
策略版本、随机池和 operation ID。

具名遭遇必须在敌人定义的 `location_key` 开始；战斗快照冻结该地点。探索遭遇从探索快照
读取地点、境界、资质、属性和装备，并记录 `exploration_id`，不读取结算时的当前状态。
境界、地点或已有行动锁任一前置不满足时，不创建会话，也不能生成任务资格证据。

## 错误码

`BATTLE_NOT_FOUND`、`BATTLE_BUSY`、`BATTLE_REQUIREMENT_MISSING`、`SKILL_NOT_AVAILABLE`、`TARGET_INVALID`、`RESOURCE_INSUFFICIENT`、`BATTLE_EXPIRED`、`BATTLE_ALREADY_SETTLED`。

## 验收

客户端伪造伤害/技能/目标被拒绝；自动行动重试不重复扣资源；超时和断线释放角色锁；探索
遭遇在 QQ 官方和 OneBot V11 上均能完成自动战斗、回放和跨重启恢复，失败不发探索冻结奖励；
PvP 结果使用所有参与者的开始快照并可回放；奖励领取不重复生成资产。

天劫试炼还必须验收：三阶段边界和阶段技能均来自服务端快照；高阶资质/装备词条、债务护盾
和阶段伤害修正进入 `ActionRecord`；重复回合不重复写行动；重启后仍能从已结算
`BattleSession` 恢复并完成试炼结算；成功只增加一次道果/功勋，失败只增加一次天劫债；QQ
官方和 OneBot V11 都能完成开始、回放和结算入口。当前终局最终战、多人 PVE 和 PvP 仍是锁定切片。
