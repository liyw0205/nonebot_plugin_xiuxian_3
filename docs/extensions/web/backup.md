# Web 域：备份与审计

`BackupArtifact`：备份 ID、范围、schema/规则/内容版本、创建时间、摘要、大小、创建者和校验状态。恢复前快照使用独立 ID。

恢复状态：`requested -> verified -> snapshot_created -> restoring -> checked -> activated`，失败进入 `failed` 并保留恢复前快照。

路径只接受数据根内文件标识；拒绝绝对路径、`..`、符号链接和设备文件。审计记录目标、前值、后值、原因、request ID 和 operation ID。