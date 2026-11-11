# 云城店铺回响

## 范围

本阶段只消费已有公开的云城移动、云城巡夜探索和云城店铺闲居，不开放锁定地点、改变
境界/名望门槛或调整探索成本、日限与奖池。云城要求金丹一层；巡夜使用 8 体力、每日 4 次
和真实遭遇战；店铺要求 `local.xuantian.cloud_city >= 200`，持续 8 小时且每日一次。

## 公开来源与玩家路径

1. `cloud_city_echoes.1`：本关开始后从青石镇或其他公开相邻地点启程，结算抵达
   `xuantian.cloud_city`。
2. `cloud_city_echoes.2`：本关开始后身在云城，完成 `explore.cloud_city_patrol` 并结算一场
   真实遭遇战胜利；未结算、战败或仅取得普通探索所得均不满足。
3. `cloud_city_echoes.3`：本关开始后按既有名望门槛新建 `idle.cloud_city_shop`，在完整窗口领取；
   逾时保底、取消、旧安排、他人记录和日限不足均不满足。

云城地方名望继续由既有派遣、项目和巡夜奖励等公开来源积累，不能用测试注入物品或降低 200
点门槛。玩家通过“云城店铺回响主线”、对应的开始/领取命令、`开始探索 云城巡夜`、
`开始挂机 云城店铺` 和分类帮助完成路径；QQ/OneBot 只负责投递，共用同一 application。

## 事务与快照

主线开始时冻结正文、目标、动作、奖励和开始时间。`travel_arrival` 只读取本人开始后的已抵达
行程；`exploration_battle_victory` 只读取本人开始后、指定模式和地点的 `settled` 且
`battle_outcome=won` 探索记录；`idle_claim` 只读取本人开始后的 `claimed` 闲居记录。目标不足
保持 `running` 且不创建领奖 operation；奖励、activity event、资产流水和 operation ledger
共用既有主线事务，失败后原请求可重试，重复 operation 只回放，输入变化返回冲突。

内容包加载时必须拒绝 unknown/locked 地点、模式、路线或奖励池；已开始快照不随热更追补目标。
