# Web 域：用例与验收

## 用例

`get_health`、`preview_operation`、`confirm_operation`、`run_operation`、`create_backup`、`verify_backup`、`restore_backup`、`query_audit`。

## 验收

未登录、无 CSRF、越权和非法路径在 application 前拒绝；参数变化使旧确认失效；同幂等键返回同结果；恢复失败保留快照；审计不含 token/密码。