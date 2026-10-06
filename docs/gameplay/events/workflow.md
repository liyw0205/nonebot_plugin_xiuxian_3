# 活动域：任务和事件状态机

```text
task: available -> active -> completed -> claimed
                         \-> failed/expired
world_event: scheduled -> open -> running -> settlement -> settled
scheduled -> cancelled
open/running -> failed
season: collecting -> frozen (claim window is derived from claim_expires_at)
daily_task_round: open -> claimed | expired
```

三界公共事件首次开轮时从内容包读取日程、目标、贡献来源与数量、个人门槛和奖励；轮次快照随
`world_event_rounds` 一同写入。来源 operation 只按该快照解释，达到结束时间后由查询、贡献或领奖事务
恢复并结算，领奖使用同一快照中的奖励。配置变化仅作用于下一轮；坏内容在创建轮次前拒绝，事务不留下
轮次或角色资产变化。

任务只能由白名单领域事件推进；事件 ID 去重。窗口键示例：`daily:<date>`、`weekly:<year-week>`、`season:<id>`。
四项常驻引路任务由本人 operation 账本中的已结算记录决定是否完成；采集只接受近郊采集最终结算且
没有战斗败退，生产只接受成功完成的订单。领奖与奖励、来源事件及 `claimed` 进度同事务提交，
另一 operation 不能再次领取；查询观战不写入这些任务表。
日课在 UTC 00:00 首次查阅或领取时创建角色轮次，并冻结任务、目标、奖励、奖励地点的名望上限及次日结束时刻；本人来源按
轮次时间窗投影且仅可归属一项任务。领取门槛为三项，窗口延至次日 24:00；逾期后不补发，新一日独立
创建轮次。配置变化只影响新轮次，已有轮次和领奖重放继续读取原快照。战斗任务只认白名单正式 PvE
胜场，并再次核对已结算战斗的角色、类型和结果；名望封顶后只记录实际增量，已有余额高于快照上限时不扣回；训练傀儡与切磋不计日课。
终局赛季按需维护：窗口结束后的首次读取或领奖事务冻结三榜；领奖期结束后的首次访问补发展示奖励。
冻结后榜单不再读取变化中的结局/战斗数据。
三界赛季冻结前分别读取公共事件贡献流水、已结算多人战斗贡献快照和宗门贡献流水；冻结后不再重算，
领奖 operation 重放返回原结果，超过 7 天窗口记录过期结果且不发放奖励。

领域前线状态为 `open -> running -> settled`，4 小时活动窗口内按 30 分钟轮次创建；加入时写入参战
快照并扣除体力。`开始领域战` 在创建正式自动战斗会话的同一事务中绑定角色、轮次和事件请求；战斗行动、胜负、
战后状态与回放均由共享战斗域结算并可恢复。来源投影只接受此绑定关系中的正式领域战胜利，不能从同地点的其他战斗
推断来源；每个来源只能消费一次。占点来源也必须属于当前轮次和角色。轮次结束由服务端恢复事务冻结全服目标、
胜方领域和个人贡献；个人达到 100 后在 24 小时内领奖。领域战赛季为 `collecting -> frozen`，
窗口结束后的首次查询或领奖事务冻结前 50 名匿名榜，冻结后不读取变化中的轮次贡献。
冻结后且仍在 7 日领奖窗口内，角色可用 `兑换领域核心 <赛季编号>` 消耗 20 个绑定碎片兑换 1 个领域核心；
兑换按角色/赛季唯一，重复 operation 只回放原结果。

虚空档案流程为：

```text
void.archive_ruins running -> settled -> archive_guard running -> won/lost
weekly task active -> complete -> claimed
three claimed -> event.archive_unlock active (7 days)
```

`探索档案遗迹` 只读取已结算航道和服务端战斗结果；失败不计 beta，重复航道或重复 operation 不重复发奖。
任务领取时在同一事务内投影来源 operation、写入周次唯一 claim、发放碎片/功勋并按三项状态激活解锁事件。

虚空前线流程为：

```text
season.void_frontier: collecting -> frozen
server source -> score projection -> weekly reward box (max 5/week)
season frozen -> anonymous player/sect snapshot -> claim (7 days)
claim window expired -> pending weekly boxes become bound merit
```

赛季查询、冻结和领奖事务都会先投影已结算航道、风暴救援、跨服宗门战胜利和自然结束联盟合同；
冻结后不再读取来源变化。周箱与赛季奖励分别按来源键和角色/赛季唯一，重放 operation 只返回原结果。
