# Web 域：路由与权限

每条路由声明 HTTP 方法、路径、权限、输入 schema、输出 DTO、是否写入、CSRF、幂等键和审计事件。

权限：`read`、`game_write`、`message`、`scheduler`、`backup`、`update`、`terminal`。未声明默认拒绝。

确认状态机：`requested -> previewed -> confirmed -> running -> succeeded/failed/cancelled`。确认令牌绑定管理员、目标摘要、参数摘要和过期时间。

API 错误：`AUTH_REQUIRED`、`CSRF_INVALID`、`PERMISSION_DENIED`、`INPUT_INVALID`、`IDEMPOTENCY_REQUIRED`、`CONFIRMATION_REQUIRED`。