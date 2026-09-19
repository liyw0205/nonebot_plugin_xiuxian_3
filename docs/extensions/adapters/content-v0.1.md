# v0.1 适配器内容基线：统一事件、文本投递与安全降级

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.1`，`rule_version=adapters-0.1.0`。适配器只把平台事件归一为 DTO、调用 application、渲染 `ReplyPlan`；不得导入或实现领域规则。

## 1. 统一 `CommandContext`

必填字段：`request_id`、`source_adapter`、`actor_id`、`scene`、`message_id`、`text`、`raw_text_digest`、`capabilities`、`can_write_assets`。可选：`group_id`、`channel_id`、`reference_message_id`、`bot_id`、`to_me`。合法 `scene` 为 `group/private/channel_group/channel_private`；无法识别、缺 actor 或缺 message ID 的事件为 `unknown`，`can_write_assets=false`。

| 原平台 | 身份字段 | 群/场景字段 | 消息字段 | 默认能力 |
|:--|:--|:--|:--|:--|
| `onebot.v11` | `user_id` | `group_id`，无则 private | `message_id`、`raw_message` | text、image、reference |
| `qq.official` | `author_id` | group/C2C/channel/direct | `id`、`content` | text、reference；Markdown/keyboard 由 AppID 开关 |
| `qq.guild` | `author_id` | `channel_id` + direct | `id`、`content` | text、Markdown、媒体按频道能力 |

## 2. v0.1 路由与操作键

| `route_key` | 文本意图 | 写入 | operation 生成规则 |
|:--|:--|:--|:--|
| `player.create` | `开始修仙` | 是 | `player.create:<adapter>:<actor_id>` |
| `player.start_seeking` | `寻仙问道` | 是 | 由 application/按钮提供稳定 operation，不以显示文本拼接 |
| `player.profile` | `我的修仙信息` / `我的状态` | 否 | 无资产 operation |
| `help.overview` | `修仙帮助` | 否 | 无 |

适配器消息 ID 只用于事件去重：`event:<adapter>:<message_id>`，TTL 10 分钟；业务 operation 由 application/安全按钮 payload 权威生成。重复事件不得重复调用写用例；同一业务 operation 仍由 ledger 做长期幂等。

## 3. 投递与降级

`ReplyPlan` 字段：文本（必需）、Markdown、键盘、媒体 URL、引用意图、导航意图。投递状态：`requested -> rendering -> sending -> sent` 或 `pending_audit/rejected/retryable_failure/permanent_failure`。文本必须始终可用；不支持 Markdown/键盘/媒体时删去不支持段并保留同一文本和引用语义，不能重执行业务 operation。

| 后端 | 事件回复 | 主动群/私聊 | 引用 | 特别规则 |
|:--|:--|:--|:--|:--|
| OneBot | 文本/图片/文件 | `send_group_msg` / `send_private_msg` | message ID | 无 `msg_seq`；发送失败仅记录结果 |
| QQ 官方 | 文本/图片/Markdown/键盘 | group / C2C | `REFIDX` | `msg_seq` 冲突最多重试 1 次 |
| QQ 频道 | 文本/Markdown/媒体 | 频道/频道私信 | 平台引用或文本降级 | 私信/公域按 scene 分开 |

投递超时：连接 5 秒、总 15 秒；媒体正文最大 8 MiB。发送失败只写 `DeliveryResult` 与审计，绝不回滚已成功的玩法 operation。

## 4. 按钮、权限与验收

v0.1 仅允许 `profile:view` 只读按钮；按钮 payload 含 `payload_version`、`request_id`、`actor_id`、`route_key`、`expires_at` 和 HMAC 签名。资产按钮在 v0.2 才开放。过期/签名/actor/scene 不匹配返回 `INTERACTION_EXPIRED`、`INTERACTION_INVALID`、`INTERACTION_ACTOR_MISMATCH`，不得调用 application。

验收：未知场景不可写；相同事件只处理一次；OneBot/QQ 各有文本 fixture；能力不足只降级；媒体/发送失败不改变角色；日志不含完整事件或凭据。