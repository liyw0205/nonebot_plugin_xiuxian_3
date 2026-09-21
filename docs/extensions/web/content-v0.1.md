# v0.1 Web 内容基线：健康、只读诊断与备份

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.1`，`rule_version=web-0.1.0`。Web 默认仅可信内网/HTTPS 部署；无管理员配置时只允许本机调试，禁止公开监听。

| 路由 | 权限 | 写入/安全 | 输出/限制 |
|:--|:--|:--|:--|
| `GET /api/v1/health` | `read` | 无写入 | readiness、迁移、功能、非敏感指标 |
| `GET /api/v1/runtime` | `read` | 无写入 | 脱敏配置、版本、任务摘要 |
| `GET /api/v1/players/{id}` | `read` | 无写入 | 角色资料；平台 ID 脱敏 |
| `GET /api/v1/operations/{id}` | `read` | 无写入 | operation 状态/摘要，不返回密钥/原始输入 |
| `GET /api/v1/audit` | `read` | 分页、最大 100 条 | 管理审计摘要 |
| `POST /api/v1/backups` | `backup` | CSRF、Idempotency-Key、二次确认 | backup operation/工件 ID |
| `POST /api/v1/backups/{id}/verify` | `backup` | CSRF、Idempotency-Key | checksum/schema/完整性报告 |

统一 envelope：`{ok,data,error,request_id}`；错误只含稳定 code、用户消息、retryable、字段错误。读取路由默认拒绝无会话/越权；写路由要求有效管理员 session、CSRF、权限和 Idempotency-Key。`backup.create` 只接逻辑名称 `[a-z0-9-]{1,48}`，不接文件路径。

备份状态：`requested -> creating -> verified -> ready` 或 `failed`；失败不生成伪工件。备份元数据包含 schema/内容/规则版本、SHA-256、大小、创建者、创建时间；文件只存在数据根 backups 目录。首版不开放任意 SQL、终端、资源调整、代码更新或任意文件路径接口。

审计字段：actor、permission、route、request/operation ID、目标、前后摘要、原因、结果、耗时；禁止 token、密码和完整外部响应。验收：无会话/无 CSRF/无权限拒绝；重复备份返回同一 operation；路径穿越拒绝；健康只依赖核心运行时/数据库/内容包；备份失败不改游戏数据。