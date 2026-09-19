# v0.4 Web 内容基线：领域运营预览与确认

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.4`，`rule_version=web-0.4.0`。

| 路由键 | 权限 | 行为 | 写入保护 |
|:--|:--|:--|:--|
| `domain.read` `/domains/{id}` | `read` | 领域能量、等级、当前战场 | 只读 |
| `sect.domain.read` `/sects/{id}/domain` | `read` | 建筑、维护、施工状态 | 只读 |
| `faction.reputation.read` | `read` | 声望、盟约、环境摘要 | 只读 |
| `event.contribution.preview` | `read` | 按已结算 operation 预览贡献 | 不直接写贡献 |
| `domain.building.preview` | `game_write` | 材料、费用、完成时间、影响范围 | CSRF/幂等，无锁定 |
| `domain.building.confirm` | `game_write` | 调用宗门建设用例 | CSRF/幂等/二次确认/原因 |

每宗门每日最多 2 次建设确认；确认前必须引用未过期 preview ID（15 分钟）、宗门/建筑/成本摘要，确认后才锁资源。Web route 只把 DTO 交给 `sect.build_domain_building`，不自行计算费用或写仓库。领域读取不泄露敌方私有构筑或未公开战场 action。

错误：`DOMAIN_PREVIEW_EXPIRED`、`DOMAIN_BUILDING_DAILY_CAP`、`DOMAIN_BUILDING_REQUIREMENT_MISSING`、`SECT_PERMISSION_DENIED`。验收：预览不锁资产；确认与按钮同一用例；重复确认不双扣；贡献 route 只读；权限/确认失败无建筑会话。