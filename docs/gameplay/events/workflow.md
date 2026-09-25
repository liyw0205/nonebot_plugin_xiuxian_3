# 活动域：任务和事件状态机

```text
task: available -> active -> completed -> claimed
                         \-> failed/expired
world_event: scheduled -> open -> running -> settlement -> settled
scheduled -> cancelled
open/running -> failed
season: collecting -> frozen (claim window is derived from claim_expires_at)
```

任务只能由白名单领域事件推进；事件 ID 去重。窗口键示例：`daily:<date>`、`weekly:<year-week>`、`season:<id>`。
终局赛季按需维护：窗口结束后的首次读取或领奖事务冻结三榜；领奖期结束后的首次访问补发展示奖励。
冻结后榜单不再读取变化中的结局/战斗数据。
三界赛季冻结前分别读取公共事件贡献流水、已结算多人战斗贡献快照和宗门贡献流水；冻结后不再重算，
领奖 operation 重放返回原结果，超过 7 天窗口记录过期结果且不发放奖励。

领域前线状态为 `open -> running -> settled`，4 小时活动窗口内按 30 分钟轮次创建；加入时写入参战
快照并扣除体力，来源投影只能在当前轮次且只能消费一次。轮次结束由服务端恢复事务冻结全服目标、
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
