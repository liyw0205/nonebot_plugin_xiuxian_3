# 战斗域：模型

`BattleSession`：战斗 ID、类型、参与者快照、敌方键、环境键、自动行动策略版本、行动序号、状态 payload、随机池版本、状态和回放日志。

天劫试炼的快照额外保存 `profile_key=battle_profile.tribulation_trial.v1`、
`tribulation_phase`、`debt_shield_bp`、债务/随机压力、三阶段敌人技能表、高阶属性和
`combat-0.6.1`。阶段由服务端根据敌方剩余气血选择，不能读取结算时的当前角色或内容配置。

`BattleResult`：战斗 ID、胜负、终局原因、回放摘要、奖励定义、待领取状态、结算 operation。

`ActionRecord`：序号、行动者、服务端策略、技能、目标、消耗、随机结果、效果、状态变化、剩余资源和规则版本。记录不可由客户端提交或修改。天劫行动状态至少包含阶段、债务护盾、阶段伤害修正、双方剩余气血。

`PartyBattleSession` 不复用单人 `BattleSession` 的参与者字段：队伍快照包含全部成员的属性、
装备和角色身份；`PartyBattleMember` 保存资产锁与释放时间；`PartyBattleReward` 以成员唯一键
记录结算。队伍战斗行动同样写入独立回放表，任一已确认成员可触发结算。
