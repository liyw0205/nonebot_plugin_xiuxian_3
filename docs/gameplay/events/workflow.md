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
