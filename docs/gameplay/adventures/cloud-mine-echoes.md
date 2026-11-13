# 云铁守望回响

## 范围

剧情只使用已经开放的玄天云铁矿区抵达、云铁探索和矿区看守路线，不开放锁定地点、
云铁矿区之外的新配方或新的经济规则。既有筑基四层、许可/矿镐/采矿辅修准入、探索成本、
闲居时长与日限、完整和逾时奖池保持不变。

## 公开来源与玩家路径

1. `cloud_mine_echoes.1`：从云城或青石镇沿公开路线抵达并结算 `xuantian.cloud_mine`。
2. `cloud_mine_echoes.2`：关卡开始后在矿区完成一次 `explore.cloud_mine`，只认服务端探索结算中
   实得至少一份 `item.material.cloud_iron`；战败、未结算和旧物资不计。
3. `cloud_mine_echoes.3`：关卡开始后新建并完整领取 `idle.cloud_mine_watch`；逾时保底、取消、
   旧安排、他人记录和日限不足不计。

主线正文、动作和重试提示由 `data/剧情/主线.json` 解析。玩家通过“云铁守望回响主线”、
“开始云铁守望回响主线 <关卡名>”和“领取云铁守望回响主线奖励 <关卡名>”进入同一
application/repository；生活帮助指向真实移动、探索和闲居命令。

## 事务与快照

主线开始时冻结正文、目标、动作、奖励和开始时间。`travel_arrival` 只查询本人开始后的已抵达
行程；`exploration_reward` 只查询本人开始后的 settled 探索结果，不读背包净数量；`idle_claim`
只查询本人开始后的 `claimed` 闲居记录，因此 `expired` 保底不会满足目标。目标不足保持 running
且不写领奖 operation。奖励、activity event、资产流水和 operation ledger 仍由通用主线事务原子
提交；写入失败可使用原 operation 重试，相同 operation 只回放原结果，输入变化返回冲突。

内容热更不改变已开始关卡快照；未知/锁定地点、探索模式、闲居路线或奖励池在加载时拒绝。旧
主线运行快照按开始时冻结的目标结算，不追补新增目标。
