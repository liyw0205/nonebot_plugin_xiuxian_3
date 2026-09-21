# 适配器域：投递和降级

`deliver(context, reply_plan) -> DeliveryResult`。

状态：`requested -> rendering -> sending -> sent`，或 `pending_audit`、`rejected`、`retryable_failure`、`permanent_failure`。

QQ 使用 `REFIDX` 引用和 `msg_seq` 重试；OneBot 使用事件/API 发送。Markdown/键盘/媒体/引用不支持时按策略降级，不能重执行业务 operation。