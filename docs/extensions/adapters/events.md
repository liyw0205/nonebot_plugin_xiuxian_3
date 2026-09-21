# 适配器域：事件与路由

去重键：adapter、bot ID、scene、平台消息 ID、事件类型。没有可靠消息 ID 的事件只允许读路径或受限去重键。

空前缀且命令量大时，按完整命令、字面前缀、正则前缀和通用 matcher 建索引。无法安全分析的正则和 `on_message` 不被误过滤。

好友/群/频道生命周期和 interaction ACK 走独立链路，不混入普通命令限流。ACK 必须 exactly-once。