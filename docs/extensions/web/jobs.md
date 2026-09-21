# Web 域：任务与消息

任务声明稳定 ID、触发器、时区、并发、超时、重试、关键性和最近结果。手动运行生成独立 run ID。

消息面板只能调用 DeliveryService，记录场景、Bot、目标、message ID、reference ID、发送状态和失败原因。Web 发送失败不能重试资产用例。

任务错误使用 `retryable` 标记；关键奖励、交易、迁移和恢复任务不能在队列满时静默丢弃。