# 战斗域：用例与验收

## 用例

`start_battle`、`submit_action`、`resolve_battle`、`claim_battle_reward`、`replay_battle`。

`submit_action` 只接收战斗 ID、行动者、技能键、目标、客户端序号和 operation ID；服务端计算伤害和状态。

## 错误码

`BATTLE_NOT_FOUND`、`BATTLE_BUSY`、`NOT_ACTIVE_TURN`、`SKILL_NOT_AVAILABLE`、`TARGET_INVALID`、`RESOURCE_INSUFFICIENT`、`BATTLE_EXPIRED`、`BATTLE_ALREADY_SETTLED`。

## 验收

伪造伤害值被忽略；非当前行动者不改变状态；行动重试不重复扣资源；超时释放角色锁；奖励领取不重复生成资产。