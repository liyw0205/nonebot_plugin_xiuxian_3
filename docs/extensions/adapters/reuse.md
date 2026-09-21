# 适配器域：复用和验收

复用上游魔改实现时记录仓库、commit/tag、许可证、本地修改和回归结果；代码隔离在 adapters/vendored 边界，不能导入业务模块。

错误码：`ADAPTER_EVENT_INVALID`、`ADAPTER_SCENE_UNKNOWN`、`DELIVERY_CAPABILITY_MISSING`、`DELIVERY_TIMEOUT`、`DELIVERY_RATE_LIMITED`、`DELIVERY_REJECTED`、`DELIVERY_PERMANENT_FAILURE`。

验收：OneBot/QQ 相同文本形成等价 Context；引用失败降级；msg_seq 只在投递层重试；interaction 只 ACK 一次；未知场景不可写资产。