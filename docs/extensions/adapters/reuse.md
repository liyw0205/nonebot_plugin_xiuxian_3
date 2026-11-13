# 适配器域：依赖边界与验收

平台 SDK 与协议库只在适配器边界内使用，领域模块不得依赖平台对象。若发行包包含第三方源代码，应保留来源、版本、许可证和本地修改说明，并验证变更不会泄漏到业务模块。

错误码：`ADAPTER_EVENT_INVALID`、`ADAPTER_SCENE_UNKNOWN`、`DELIVERY_CAPABILITY_MISSING`、`DELIVERY_TIMEOUT`、`DELIVERY_RATE_LIMITED`、`DELIVERY_REJECTED`、`DELIVERY_PERMANENT_FAILURE`。

验收：OneBot/QQ 相同文本形成等价 Context；引用失败降级；msg_seq 只在投递层重试；interaction 只 ACK 一次；未知场景不可写资产。
