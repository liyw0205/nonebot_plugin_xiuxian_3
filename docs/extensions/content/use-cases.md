# 数据内容域：用例与验收

## 用例

`validate_content_bundle`、`preview_content_release`、`publish_content_release`、`run_migration`、`rollback_content_release`。

## 错误码

`CONTENT_SCHEMA_INVALID`、`CONTENT_KEY_DUPLICATE`、`CONTENT_REFERENCE_MISSING`、`CONTENT_VALUE_INVALID`、`CONTENT_VERSION_ACTIVE`、`MIGRATION_PRECHECK_FAILED`、`MIGRATION_FAILED`、`RELEASE_CONFIRMATION_REQUIRED`。

## 验收

缺失引用和非法权重拒绝发布；内容重复加载不重复奖励；迁移失败可恢复；新操作读取新版本，历史结算读取原版本。