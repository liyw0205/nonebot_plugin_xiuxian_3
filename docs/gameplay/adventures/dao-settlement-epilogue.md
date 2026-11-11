# 道统余响：公开轮值后记

## 范围

本后记消费已经开放的 `dao.origin_gate`、`dao_service`、
`idle.dao_settlement_watch` 和 `dispatch.dao_service`。它不替代
`story.mainline.dao_echoes` 的建设者、见证者、远行者三线，也不开放
locked 的道统地点或未来道统内容。

## 玩家路径

`dao.origin_gate` 沿 `region.dao.origin` 的公开零成本边抵达 `dao_service`。
随后以道统路线准入 `idle.dao_settlement_watch`，完整等待并领取十二小时看守；
最后按 `dispatch.dao_service` 的既有境界/服务信誉、体力、精力、日限、风险和奖励
合同接受并在到期后结算成功一次。闲居的逾时保底、派遣的 failed/partial/delayed
结果都不替代剧情目标。

## 主线合同

`story.mainline.dao_settlement` 的三个开放关卡为：

1. `dao_settlement.1`：本关开始后的 `travel_arrival`，目标为公开抵达 `dao_service`。
2. `dao_settlement.2`：本关开始后的 `idle_claim`，目标为完整领取 `idle.dao_settlement_watch`。
3. `dao_settlement.3`：本关开始后的 `dispatch_success`，目标为本人
   `dispatch.dao_service` 的 settled/success 事件。

开始主线时冻结目标、正文、行动、奖励和重试文案。结算只统计本关开始后的本人记录；
旧记录、他人记录、未结算安排、失败或部分结果不推进。目标不足时主线保持 running，
奖励事务失败可用原 operation 重试，重复 operation 只回放。

## 边界

不降低道统路线、服务信誉或派遣成本，不修改闲居/派遣奖池、时长、日限和随机权重，
不把地方名望当作服务信誉，不写生产玩家库或真实平台消息。官方主线种子变更须在
`scripts/seed_migrations.json` 登记旧/新 SHA-256 与真实 Git provenance，并保留未知/自定义 JSON。
