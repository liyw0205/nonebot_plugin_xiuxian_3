# v0.5 Web 内容基线：虚空状态与申请式航线

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.5`，`rule_version=web-0.5.0`。

| 路由键 | 权限 | 语义 | 禁止事项 |
|:--|:--|:--|:--|
| `void.routes.read` | `read` | 航道、节点、开放/风险状态 | 不显示他人精确位置 |
| `void.market.read` | `read` | 库存、刷新、个人限额摘要 | 不绕市场锁/限额 |
| `sect.war.read` | `read` | 跨服报名/战场状态 | 不改 roster |
| `economy.void_summary.read` | `read` | 虚空资产/订单聚合 | 不显示私密订单内容 |
| `void.route.request` | `game_write` | 提交航线申请至 application | Web 不直接扣锚 |
| `content.publish` | `update` | 沿用 v0.3 发布状态机 | 必须预览/确认 |

`void.route.request` 输入 route key、角色、Idempotency-Key；应用层校验炼虚、锚、抗性、不稳定、地点与队伍，再创建航线 operation。重复 request 返回原会话；Web 不可直接调整虚空锚/声望/订单。所有虚空和发布操作写审计原因、内容/规则版本、operation 结果。

错误：`VOID_ROUTE_UNAVAILABLE`、`VOID_ROUTE_REQUEST_CONFLICT`、`VOID_WEB_PERMISSION_DENIED`。验收：申请失败不扣锚；重复返回同会话；内容发布不绕二次确认；只读路由不暴露跨服私密数据。