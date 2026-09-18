# nonebot_plugin_xiuxian_3

从零设计的 NoneBot 修仙文字游戏插件。

本仓库是一个**新实现的设计与开发基线**，不是
`nonebot_plugin_xiuxian_2_pmv` 的代码复制或目录改名。旧项目只作为行为
参考，用来整理玩家可见功能、运维约束和需要兼容的协议；实现、数据模型、
测试和迁移方案都在本仓库重新决定。

当前阶段：**规格冻结与架构设计**。仓库暂不提供可运行插件，后续开发应
严格按文档逐个完成垂直切片。

## 目标

- 为 QQ 群/私聊提供可长期维护的修仙文字游戏。
- 同时支持 OneBot V11 与 QQ 官方适配器，并让领域规则不依赖平台 SDK。
- 覆盖修炼、战斗、社交、经济、娱乐、管理和 Web 运维能力。
- 让资产变化具备明确事务、幂等键、审计记录和可恢复的失败语义。
- 在保留旧命令与玩家数据迁移路径的前提下，允许内部实现完全重写。

## 文档入口

| 文档 | 内容 |
|:--|:--|
| [产品规格](docs/product-spec.md) | 用户、玩法循环、功能范围和非目标 |
| [功能目录](docs/feature-catalog.md) | 按领域拆分的完整能力地图 |
| [命令与交互面](docs/command-surface.md) | 命令、别名、权限和消息行为约束 |
| [领域与数据模型](docs/domain-model.md) | 核心实体、不变量、资产和迁移原则 |
| [目标架构](docs/architecture.md) | 模块边界、依赖方向和启动生命周期 |
| [适配器与 Web](docs/adapters-and-web.md) | OneBot/QQ 消息归一化、Web API 与权限 |
| [运行与安全](docs/operations.md) | 配置、任务、备份、日志和安全边界 |
| [测试策略](docs/testing.md) | 测试分层、验收门槛和回滚演练 |
| [开发路线](docs/roadmap.md) | 从空仓库到可发布版本的阶段计划 |
| [参考基线](docs/reference-baseline.md) | 参考项目的范围、证据等级和排除项 |
| [决策记录](docs/adr/) | 影响长期实现的架构决策 |

## 开发约定

1. 先完成文档对应的领域用例和测试，再接入命令或 Web。
2. 业务规则只能依赖领域端口，不能直接导入 NoneBot、Flask 或 SQLite。
3. 任何灵石、修为、物品、体力、积分、称号和交易状态变化都必须经过
   一个可追踪的 operation，并支持重复请求不重复扣发。
4. 命令名称和外部 URL 属于兼容协议；内部类名、表结构和包布局不属于协议。
5. 运行数据、密钥、用户数据、备份和媒体缓存永远不提交到 Git。

## 参考项目

行为参考必须来自 GitHub 远端 `main` 的**独立干净克隆**。参考目录不是本仓库
的必需文件；使用前先执行：

```bash
git clone --branch main --single-branch \
  https://github.com/liyw0205/nonebot_plugin_xiuxian_2_pmv.git \
  ../nonebot_plugin_xiuxian_2_pmv_upstream
```

原目录 `../nonebot_plugin_xiuxian_2_pmv` 可能包含本地重构或未提交改动，严禁
作为参考证据。若独立目录不存在，goal 必须先创建它；不能通过读取同名旧目录
来代替。新项目以干净主分支的运行时观察和本仓库文档为准，不直接复制实现文件。

## 当前仓库状态

本首提交只包含规格文档、ADR 和 Git 忽略规则。后续使用 goal 时，建议从
`docs/roadmap.md` 的 P0 开始，每个阶段形成独立、可测试、可回滚的提交。
