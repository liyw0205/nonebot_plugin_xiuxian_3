# v0.3 Web 内容基线：内容发布与受控恢复

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.3`，`rule_version=web-0.3.0`。内容发布与恢复均为高风险操作，必须走 application/任务状态机，Web 不直接替换文件或数据库。

| 路由键 | 权限 | 要求 | 结果 |
|:--|:--|:--|:--|
| `faction.read` | `read` | 无写入 | 三界声望、盟约、事件状态 |
| `season.current.read` | `read` | 冻结榜单/个人分数 | 赛季快照 |
| `economy.summary.read` | `read` | 脱敏聚合 | 钱包、锁定资产、订单统计 |
| `content.preview` | `update` | CSRF、Idempotency-Key | 版本差异/影响报告 |
| `content.publish` | `update` | preview ID、CSRF、二次确认、Idempotency-Key、原因 | 激活 operation |
| `backup.restore` | `backup` | 工件 ID、CSRF、二次确认、Idempotency-Key、原因 | 恢复 operation |

发布状态：`requested -> preview_verified -> backup_created -> activating -> health_checked -> active`；失败进入 `failed` 并保持前版本。恢复状态：`requested -> verified -> snapshot_created -> restoring -> integrity_checked -> active`；失败保留恢复前快照、状态 `failed`。两者在开始写入前停止新资产请求，已有关键 operation 等待/恢复；不重新结算历史 operation。

二次确认令牌 10 分钟，绑定管理员、route、目标版本/工件、请求摘要；参数变更即失效。发布/恢复重复 request 返回同一 operation。错误：`WEB_CONFIRMATION_REQUIRED`、`CONTENT_PREVIEW_STALE`、`BACKUP_ARTIFACT_INVALID`、`RESTORE_WRITE_DRAIN_TIMEOUT`。验收：无预览不能发布；恢复前必建快照；失败不丢旧版本/数据库；Web 不提供批量发奖/SQL/终端。