# 修仙 3 文档索引

## 玩家与安装

- [当前可用能力](availability.md)：v0.1.41 的开放玩法与能力边界。
- [安装、配置与更新](installation.md)：Linux、Termux、Windows、Docker 和已有 NoneBot 宿主。
- [玩家使用指南](usage.md)：角色创建、修炼、探索、挂机、剧情与委托流程。
- [运行与安全](operations.md)：配置优先级、备份、恢复、权限与运行安全。
- [QQ 消息能力](qq-markdown-reference.md)：Markdown、蓝字和键盘消息约定。

## 内容与行为合同

- [完整内容设计](content-development.md)：境界、世界、玩法与长期内容范围。
- [数据内容合同](content-data-contract.md)：JSON 字段、引用、数据来源与真实消费者。
- [通用行为合同](content-development-contract.md)：事务、幂等、快照、错误处理和数据库变更。
- [消息文案规范](messaging-copywriting.md)：玩家消息的语气、错误提示和适配器降级。
- [测试与验收](testing.md)：按变更范围选择的本地验证规则。
- [发布与种子迁移](release-distribution.md)：Release 资产、用户数据保护与迁移回退。
- [开发与维护指南](development-guide.md)：代码/内容边界、运行链路与扩展流程。
- [运行能力状态判定](current-status.md)：区分玩家可用能力、合同状态和验收证据。
- [有限阶段规划模板](implementation-plan.md)：范围、依赖、交付和回滚边界。
- [外部参考与来源管理](reference-sources.md)：玩法参考、第三方代码来源与许可证边界。
- [适配器来源与升级核验](adapter-upstream-review.md)：SDK 实际加载来源及适配器验收边界。

## 领域参考

- [基础领域](foundation/README.md)：角色、境界、道途、属性、物品和养成。
- [玩法领域](gameplay/README.md)：世界、探索、战斗、生产、经济、社交、生活与剧情。
- [扩展领域](extensions/README.md)：适配器、Web 运维和内容包。
- [架构](architecture.md)：模块边界、依赖方向和运行时组成。
- [运行框架](runtime-framework.md)：宿主生命周期、命令路由和持久化流程。
- [适配器与 Web 契约](adapters-and-web.md)：事件归一化、消息投递、管理接口与安全约束。

各领域 README 是该领域的阅读入口；`model.md`、`workflow.md`、`use-cases.md` 与内容快照分别描述实体、行为和具体数据。玩家是否能使用某项能力以[当前可用能力](availability.md)及实际公开入口为准，配置记录存在不等同于入口已开放。
