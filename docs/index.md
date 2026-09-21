# 修仙 3 文档总索引

本文档用于开发阶段按主题加载上下文。`xiuxian3-design.md` 是总纲；每个域目录的 `README.md` 是域索引，`model.md`、`workflow.md`、`use-cases.md` 等文件是实现细节权威。顶层同名文档保留为概览，不再承担全部细节。

## 一、设计总纲

| 文档 | 内容 | 状态 |
|:--|:--|:--|
| [修仙 3 总设计](xiuxian3-design.md) | 项目定位、新手流程、世界观、境界、道途、资源、总体循环和子文档裁决原则 | 主文档 |
| [实施计划](implementation-plan.md) | P0-P8 依赖、首版垂直切片、风险、验收与回滚 | 执行权威 |
| [完整内容开发总表](content-development.md) | 全部境界、功能域、发布边界、首版范围、稳定键依赖和完整切片验收 | 内容开发唯一权威 |
| [版本内容开发合同](content-development-contract.md) | 全部 `content-v*.md` 的字段、版本、事务、幂等、随机、失败、发布和回滚约束 | 内容工程权威 |
| [上游参考与复用边界](reference-sources.md) | 上游文档的通用玩法参考、适配器复用范围和禁止事项 | 已整理 |
| [基础域目录](foundation/) | 角色、境界、道途、属性、资源、物品和构筑养成的分文件规格 | 细节权威 |
| [核心玩法域目录](gameplay/) | 世界、探索、战斗、生产、社交、经济、活动、常驻经营、道历运营、冒险主线和灵兽灵骑的分文件规格 | 细节权威 |
| [扩展域目录](extensions/) | 适配器、Web 运营和数据内容的分文件规格 | 细节权威 |

各域的 `content-v0.1.md` 至 `content-v0.6.md` 是历史发布快照，不是并列的开发规范。
全部境界和功能的完整开发范围以[完整内容开发总表](content-development.md)为准；
快照只表示某个 `content_version` 的开放键和值，不能要求实现按版本逐个开发。
所有版本内容文件同时受 [版本内容开发合同](content-development-contract.md) 约束。

发布路线：v0.1 新手和玄天界基础闭环；v0.2 金丹、玄天界扩区、宗门/市场成熟和魔界入口；v0.3 元婴、魔界/妖界正式区域、多人副本、阵营战争和赛季；v0.4 化神、领域和跨界深层；v0.5 炼虚、虚空航道和跨服宗门战；v0.6 合道、渡劫、飞升和终局赛季。该路线描述内容快照，不是代码开发顺序。

## 二、基础系统

| 文档 | 内容 | 状态 |
|:--|:--|:--|
| [角色域](foundation/player/) | 新用户、寻仙问道、凡人、身份、资质和角色状态 | 分文件 |
| [境界域](foundation/progression/) | 公共境界、每境十层、修为、道基、突破和渡劫 | 分文件 |
| [道途域](foundation/paths/) | 六大道途、辅修、选择、切换和状态 | 分文件 |
| [属性域](foundation/stats/) | 基础属性、派生属性、定点计算、来源和快照 | 分文件 |
| [资源与物品域](foundation/items/) | 资源、背包、功法、技能、装备、丹药和奖励 | 分文件 |

## 三、核心玩法

| 文档 | 内容 | 状态 |
|:--|:--|:--|
| [世界域](gameplay/world/) | 三界、洞天福地、地点和移动 | 分文件 |
| [探索域](gameplay/exploration/) | 采集、历练、悬赏、秘境和结算 | 分文件 |
| [战斗域](gameplay/combat/) | PVE、行动、技能、状态、回放和奖励 | 分文件 |
| [生产域](gameplay/production/) | 采集、炼丹、炼器、布阵和委托 | 分文件 |
| [社交域](gameplay/social/) | 宗门、师徒、队伍、服务和权限 | 分文件 |
| [经济域](gameplay/economy/) | 钱包、市场、订单、锁定和流水 | 分文件 |
| [活动域](gameplay/events/) | 任务、世界事件、轮次、排行和奖励 | 分文件 |
| [常驻经营域](gameplay/livelihood/) | 洞府、灵田、城镇委托、商贸运输、地方名望和生活循环 | 分文件 |

## 四、扩展和运行

| 文档 | 内容 | 状态 |
|:--|:--|:--|
| [适配器域](extensions/adapters/) | DTO、投递、降级、事件路由和复用边界 | 分文件 |
| [Web 运营域](extensions/web/) | 路由、权限、任务、消息、备份和审计 | 分文件 |
| [数据内容域](extensions/content/) | 内容包、校验、发布、迁移和回滚 | 分文件 |
| [静态数据盘点](static-data-inventory.md) | 境界、物品、法器、配方及首版内容键清单 | 已盘点，冲突已转入总表 |
| [测试与验收](testing.md) | 测试分层、资产用例、适配器契约和恢复演练 | 工程规范 |
| [目标架构](architecture.md) | 模块边界、依赖方向、生命周期和 feature manifest | 工程规范 |
| [运行与安全](operations.md) | 配置、任务、备份、队列和安全底线 | 工程规范 |
| [运行基础框架](runtime-framework.md) | SQLite/WAL、寻仙问道用例、多适配器入口和并发边界 | 已实现骨架 |
| [适配器与 Web 契约](adapters-and-web.md) | 已有的抽象接口约束 | 工程规范 |

## 五、阅读顺序

首次了解项目：

1. `xiuxian3-design.md`
2. `content-development.md`，确定首版范围和完整境界/功能路线
3. `foundation/README.md`，再进入对应域的模型、流程和用例
4. `gameplay/README.md`，再进入对应玩法域目录；特色运营先读 `routine/`、`adventures/`、`companions/`
5. `extensions/README.md`，再进入对应扩展域目录
6. 只有需要复原历史发布参数时才读取对应的 `content-v*.md`

开始实现一个功能：

1. 先读对应域目录的 `README.md`。
2. 再读该域的 `model.md`、`workflow.md`、`use-cases.md`。
3. 跨域资源读取 `foundation/items/`，跨域数值读取 `foundation/stats/`。
4. 涉及消息时读 `extensions/adapters/`；涉及管理员或数据时读 `extensions/web/` 和 `extensions/content/`。
5. 最后按 `testing.md` 补齐测试与回滚验证。

开始首版新手闭环时，先读 `content-development.md` 的 MVP-1 范围，再读
`implementation-plan.md` 的当前切片和角色域模型；它们共同冻结
`new_user -> 寻仙问道 -> mortal -> seeker -> cultivator` 状态机、初始资源、引导与六大道途选择。
不得以旧项目或历史快照推断本文未声明的规则。

## 六、统一文档约定

每个玩法文档都必须说明：目标、玩家流程、实体字段、状态机、前置条件、用例输入输出、消耗、产出、随机性、冷却、失败/取消/过期、幂等、权限、错误码、观测字段、验收样例和首版范围。

文档中的数值为策划基线，统一使用 `rule_version` 管理。实现可以调整参数，但必须同时更新公式测试、内容版本和变更记录。
