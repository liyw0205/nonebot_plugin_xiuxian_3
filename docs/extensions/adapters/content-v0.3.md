# v0.3 适配器内容基线：多 Bot、审核与媒体缓存

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.3`，`rule_version=adapters-0.3.0`。多 Bot 仅影响投递，不影响 actor、operation、奖励或玩法路由。

## 1. Bot 路由

| 场景 | 首选 | 备用 | 失败策略 |
|:--|:--|:--|:--|
| 群聊战斗 | 最近活跃且有能力 Bot | 同群最低负载 Bot | 切换一次，之后 `pending_audit` |
| 频道活动 | 频道绑定 Bot | 全局活动 Bot | 文本降级后切换一次 |
| 私聊奖励 | 最近交互 Bot | 默认 Bot | 失败仅记录，不改奖励 operation |

选择记录 `bot_id`、能力快照、scene、route 和 request ID。备用切换至多一次；不能因不同 Bot 重新调用同一 application operation。

## 2. 审核与媒体

`DeliveryResult` 状态支持 `pending_audit`：审核等待最长 10 分钟，超时转 `permanent_failure` 并通知管理员，不重放资产。媒体上传使用 SHA-256 内容缓存，键为 `sha256:size:mime`；缓存 TTL 图片 24h、音视频 6h、文件 1h。缓存命中仍校验目标 Bot 能力和大小限制。

媒体上传最大 20 MiB、连接 5 秒、总 20 秒；拒绝未知 MIME、内网 URL、重定向 >3、压缩炸弹和未声明大小的流。原始平台响应只存脱敏摘要。

## 3. 频道生命周期与验收

频道成员离开时仅清理频道会话/待发送记录，不删角色或资产；频道私信引用不支持时降级文本。动态 route manifest 重建必须原子：先校验冲突，再交换索引。

错误：`DELIVERY_BOT_UNAVAILABLE`、`DELIVERY_PENDING_AUDIT`、`MEDIA_TOO_LARGE`、`MEDIA_UNSAFE_URL`、`MEDIA_UPLOAD_TIMEOUT`、`ROUTE_MANIFEST_CONFLICT`。验收：多 Bot 切换一次；审核不重放奖励；缓存不跨用户泄露私有文件；频道退出不删玩家；动态索引失败保留旧索引。