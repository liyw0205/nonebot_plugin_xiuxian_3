# v0.6 Web 内容基线：终局只读与结局确认

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.6`，`rule_version=web-0.6.0`。

| 路由键 | 权限 | 规则 |
|:--|:--|:--|
| `dao.origin.read` | `read` | 道果进度、道统状态、脱敏来源 |
| `tribulation.read` | `read` | 天劫会话只读状态/回放摘要 |
| `season.final.read` | `read` | 终局榜冻结快照 |
| `ending.read` | `read` | 结局展示摘要，不含平台用户 ID |
| `ascension.confirm` | `game_write` | 确认飞升/留界，需单次 token、CSRF、二次确认、幂等、原因 |

确认 token 有效 10 分钟，绑定角色快照、ending key、season key、管理员和请求摘要；任一字段改变即失效。route 调用同一 `ascension.choose_ending` 用例，成功后无撤销 API；恢复只能走离线/受控恢复流程并保留审计。Web 不得替代玩家的战斗前置或发放终局资源。

错误：`ASCENSION_CONFIRMATION_TOKEN_INVALID`、`ASCENSION_ENDING_ALREADY_RESOLVED`、`ASCENSION_REQUIREMENT_MISSING`。验收：token 不可跨角色/管理员；重复确认回放；读路由匿名；无二次确认无写入；恢复审计完整。