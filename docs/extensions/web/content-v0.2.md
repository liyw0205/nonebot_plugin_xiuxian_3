# v0.2 Web 内容基线：只读游戏运营与内容校验

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.2`，`rule_version=web-0.2.0`。新增路由均为只读或 dry-run；不允许 Web 直接改角色、背包、订单或数据库。

| 路由键/路径 | 权限 | 语义 | 限制 |
|:--|:--|:--|:--|
| `progression.read` `/players/{id}/progression` | `read` | 境界、阶段、修为、突破状态 | 不显示随机种子 |
| `inventory.read` `/players/{id}/inventory` | `read` | 物品、数量、绑定、耐久 | 默认分页 50 |
| `market.read` `/market/orders` | `read` | 订单、锁定摘要、过期 | 不暴露买卖方平台 ID |
| `events.active` `/events/active` | `read` | 轮次、截止、个人进度 | 仅当前管理员可查看完整进度 |
| `content.validate` `/content/validate` | `update` | 草稿内容 dry-run 校验 | 不激活、不写运行数据 |

`content.validate` 输入为受限上传/已暂存内容包标识，最大 2 MiB；校验引用闭合、稳定键、版本单调、数值范围、奖励/前置可达性、链接/包摘要。返回报告 ID，报告保存 24 小时于运行目录，读取需同一管理员权限。POST 均要求 CSRF、request_id、Idempotency-Key；即使 dry-run 也去重，避免高耗校验风暴。

备份创建/校验继续保留。资源调整、数据库编辑、终端、代码更新保持关闭。错误：`CONTENT_DRAFT_TOO_LARGE`、`CONTENT_VALIDATION_FAILED`、`CONTENT_REPORT_EXPIRED`、`WEB_PAGE_LIMIT_INVALID`。验收：校验不激活版本；非法上传/路径拒绝；重复报告稳定；只读查询不触发资产 operation。