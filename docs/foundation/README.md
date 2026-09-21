# 修仙 3 基础域索引

| 域 | 目录 |
|:--|:--|
| 角色 | [player/](player/) |
| 境界 | [progression/](progression/) |
| 道途 | [paths/](paths/) |
| 属性 | [stats/](stats/) |
| 资源与物品 | [items/](items/) |
| 修炼与构筑养成 | [advancement/](advancement/) |

每个域目录的 README 是入口；model、workflow、use-cases 是实现细节。

全部 `content-v*.md` 同时遵守 [版本内容开发合同](../content-development-contract.md)。内容文件显式定义稳定键、数值和版本覆盖；未写字段采用合同中的事务、随机、失败、权限、观测和回滚规则。

## v0.1 内容入口

- [角色、新手与入道内容](player/content-v0.1.md)
- [境界内容](progression/content-v0.1.md)
- [道途内容](paths/content-v0.1.md)
- [属性内容](stats/content-v0.1.md)
- [资源与物品内容](items/content-v0.1.md)
- [生产配方内容](../gameplay/production/content-v0.1.md)
- [闭关、道脉、体质、神通与法器养成](advancement/content-v0.1.md)