# 适配器与 Web 契约

## 1. 事件归一化

领域只接收统一的 `CommandContext`：`actor_id`、`scene`、`group_id`（可空）、
`message_id`、原始文本摘要、回复引用和能力声明。适配器负责从 OneBot V11、
QQ 官方群/C2C、频道公域/私信事件补齐这些字段。

统一场景：`group`、`private`、`channel_group`、`channel_private`、`unknown`。
频道公域按群语义处理，频道私信按私聊语义处理；无法识别的事件不得进入资产
写入用例。

## 2. 消息投递

业务只返回 `ReplyPlan`，由投递门面根据 Bot 能力选择文本、Markdown、键盘、
图片、音频、视频、文件、引用或合并转发。OneBot 和 QQ 的平台差异只能存在
于适配器后端。

投递门面必须提供：

- 群聊、私聊、频道群、频道私信的主动发送和事件回复。
- 明确的 message id/reference id 语义；不能混用。
- 媒体大小、超时、SSRF、缓存和上传失败边界。
- QQ `msg_seq` 冲突重试、interaction ACK exactly-once 和事件去重。
- 发送成功、待审核、拒绝、可重试失败的统一结果。

消息记录、撤回、广播和限流通过独立端口实现，不让玩法直接调用适配器 SDK。

## 3. Web 面板

Web 是运维和受控运营入口，不是第二套领域逻辑。页面/API 必须调用相同的
application use case 或只读 query service。

### 页面分组

| 分组 | 能力 |
|:--|:--|
| 首页/状态 | Bot、玩家、资源、版本、健康和运行指标 |
| 配置 | NoneBot/插件配置、适配器绑定、能力开关、脱敏预览 |
| 游戏运营 | 活动、奖励中心、受控命令、经济流水、用户搜索 |
| 消息 | 会话、历史、发送、撤回、广播、媒体和贴图 |
| 数据 | 只读表/查询、受控编辑、迁移状态和备份 |
| 任务 | 任务清单、启停、计划覆盖、手动运行、执行结果 |
| 运维 | 日志、备份/恢复、更新、健康检查和高风险终端 |

### API 约束

- 新 API 使用 `/api/v1/`，统一 JSON envelope：`ok`、`data`、`error`、`request_id`。
- 写请求需要管理员会话、CSRF、权限声明和输入 schema；资产写请求还需要
  `Idempotency-Key`。
- 未声明权限的路由默认拒绝。权限至少分为 `read`、`game_write`、`message`、
  `scheduler`、`backup`、`update`、`terminal`。
- 错误返回稳定的 `code`、用户可读消息、是否可重试和字段错误；不得泄露 SQL、
  token、文件绝对路径或外部服务密钥。
- 文件下载、备份、恢复和上传只接收允许目录内的文件标识；拒绝绝对路径、
  `..`、符号链接和设备文件。

### 登录与安全

默认使用 NoneBot `SUPERUSERS` 或显式管理员 ID 白名单。生产部署要求 HTTPS
或可信内网、Host 白名单、Secure/HttpOnly Cookie、CSRF、登录审计和会话过期。
终端、配置密钥、恢复备份和更新操作需要二次确认。没有管理员配置时只允许
本机调试，不得默认为公网开放。

## 4. 能力降级

QQ 不支持 Markdown/键盘/引用时，适配器降级为纯文本；媒体不可用时返回可读
的失败提示；降级不能改变用例结果或重复执行资产操作。
