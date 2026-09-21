# 扩展：Web 与运营

## 1. 定位

Web 是运维、查询和受控运营入口，不是第二套游戏逻辑。所有资产写入调用 application use case，查询调用 query service。

## 2. 页面分组

- 首页：运行状态、Bot、版本、玩家概览和健康检查。
- 配置：非密钥配置、适配器能力、开关和脱敏预览。
- 游戏运营：活动、奖励、受控补偿、玩家查询和经济流水。
- 消息：会话、收发记录、引用、撤回、广播和媒体。
- 数据：只读查询、迁移状态、内容版本和受控修复。
- 任务：任务列表、启停、手动运行、重试和执行记录。
- 备份：创建、校验、下载、恢复前快照和恢复结果。
- 日志：过滤、脱敏、错误关联和 operation 追踪。

## 3. 权限

权限至少分为：`read`、`game_write`、`message`、`scheduler`、`backup`、`update`、`terminal`。

未声明权限默认拒绝。管理员操作记录操作者、目标、原因、前值、后值、request ID 和 operation ID。

## 4. API

新 API 使用 `/api/v1/`，统一返回：

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "request_id": "..."
}
```

写请求需要管理员会话、CSRF、输入 schema 和幂等键。错误不得暴露 SQL、绝对路径、token 或外部服务完整响应。

## 5. 高风险操作

终端、配置密钥、数据库修复、恢复备份、更新代码、批量发奖和批量资源调整需要二次确认。确认内容包括目标、影响范围、预计结果和回滚点。

## 6. 消息面板

消息面板调用统一投递服务，记录场景、Bot、目标、消息 ID、引用 ID、发送状态和失败原因。Web 主动发送不直接调用平台 SDK。

## 7. 任务面板

任务声明稳定 ID、触发器、时区、并发策略、超时、重试、是否关键资产任务和最近结果。手动运行生成独立 run ID，不能绕过权限和幂等。

## 8. 备份恢复

恢复流程：停止写入 -> 校验备份 -> 创建当前快照 -> 恢复到受控临时目录 -> 执行迁移和完整性检查 -> 只读冒烟 -> 原子替换 -> 写入审计。

恢复失败保留恢复前快照。下载和上传只允许数据根目录内的文件标识，不接受绝对路径、`..`、符号链接和设备文件。

## 9. 公网安全

生产环境要求 HTTPS 或可信内网、Host 白名单、Secure/HttpOnly Cookie、CSRF、登录过期、限流和审计。没有管理员配置时只允许本机调试，不默认公网开放。

## 10. 首版范围

首版实现只读健康页、配置脱敏、任务状态、备份创建和审计查询。数据库编辑、更新、终端、广播和批量运营后置。

## 11. 实现合同

### 11.1 路由声明

每个 Web 路由声明：HTTP 方法、路径、权限、输入 schema、输出 DTO、是否写入、是否需要 CSRF、幂等键要求和审计事件键。

示例：

```text
POST /api/v1/operations/{operation_id}/retry
permission: scheduler
csrf: required
idempotency: required
audit_event: operation.retry
```

未声明路由默认拒绝，未知字段默认拒绝或显式忽略并记录校验结果。

### 11.2 管理操作状态

高风险操作使用：

```text
requested -> previewed -> confirmed -> running -> succeeded/failed/cancelled
```

确认令牌绑定管理员、目标摘要、过期时间和操作参数摘要，参数变化后必须重新预览和确认。

### 11.3 管理操作状态机与用例

```text
requested -> previewed -> confirmed -> running -> succeeded/failed/cancelled
```

基础用例包括：`get_health`、`preview_operation`、`confirm_operation`、`run_operation`、`create_backup`、`verify_backup`、`restore_backup` 和 `query_audit`。所有写用例返回操作 ID、状态、审计事件和是否可重试。

错误码：`AUTH_REQUIRED`、`CSRF_INVALID`、`PERMISSION_DENIED`、`INPUT_INVALID`、`IDEMPOTENCY_REQUIRED`、`CONFIRMATION_REQUIRED`、`PATH_FORBIDDEN`、`BACKUP_INVALID`、`OPERATION_NOT_RETRYABLE`。

### 11.4 备份对象

`BackupArtifact` 保存备份 ID、数据范围、schema 版本、规则/内容版本、创建时间、文件摘要、大小、创建者和校验状态。恢复前快照使用独立 ID，不能覆盖原备份。

### 11.5 API 错误码

`AUTH_REQUIRED`、`CSRF_INVALID`、`PERMISSION_DENIED`、`INPUT_INVALID`、`IDEMPOTENCY_REQUIRED`、`CONFIRMATION_REQUIRED`、`PATH_FORBIDDEN`、`BACKUP_INVALID`、`OPERATION_NOT_RETRYABLE`。

错误返回 `request_id`、稳定 code、用户消息和 `retryable`；生产环境不返回 traceback。

### 11.6 验收样例

1. 未登录、无 CSRF 或无权限请求在 application 执行前被拒绝。
2. 高风险参数变化后旧确认令牌不可用。
3. 同一幂等键重试返回同一管理操作结果。
4. 恢复失败保留恢复前快照并可查询失败原因。
5. 审计记录不包含 token、密码和完整用户凭据。
