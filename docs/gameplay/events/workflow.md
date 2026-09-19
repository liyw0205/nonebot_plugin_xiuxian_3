# 活动域：任务和事件状态机

```text
task: available -> active -> completed -> claimed
                         \-> failed/expired
world_event: scheduled -> open -> running -> settlement -> settled
scheduled -> cancelled
open/running -> failed
```

任务只能由白名单领域事件推进；事件 ID 去重。窗口键示例：`daily:<date>`、`weekly:<year-week>`、`season:<id>`。