# 扩展：适配器域

适配器域将 OneBot V11 和 QQ 官方事件归一为 xiuxian3 DTO，并负责消息投递与能力降级。

当前 QQ 官方和 OneBot V11 已接入同一 application 路由；普通消息、Markdown/合并转发的
能力差异只在投递层降级。新增适配器不得绕过[当前可用能力](../../availability.md)中的运行时边界。

- [统一 DTO](context.md)
- [投递和能力降级](delivery.md)
- [事件与路由](events.md)
- [复用和验收](reuse.md)
- [运行时来源与升级核验](../../adapter-upstream-review.md)
