# nonebot_plugin_xiuxian_3

从零设计的 NoneBot 修仙文字游戏插件。

本仓库是一个**全新设计的修仙文字游戏**，不是
`https://github.com/liyw0205/nonebot_plugin_xiuxian_2_pmv` 的代码复制或目录改名。上游公开文档用于通用玩法
参考，上游魔改适配器用于兼容层复用；境界、道途、数值、数据模型和命令都在本仓库重新决定。

当前阶段：基础成长、经营、高阶境界状态机和部分服务端自动回合 PVE 已接入可测试切片；
探索遭遇和双人队伍 PVE 已开放，三人以上副本、终局最终战与 PvP 仍未开放。当前可运行边界和下一切片以
[`docs/current-status.md`](docs/current-status.md) 为准，后续开发按可测试的垂直切片推进。

## 目标

- 为 QQ 群/私聊提供可长期维护的修仙文字游戏。
- 支持“新用户 → 寻仙问道 → 凡人 → 道途分支 → 感气修炼”的清晰首版流程。
- 以玄天界、魔界、妖界和洞天/福地构成可扩展世界。
- 以公共境界、六大道途和炼丹/炼器/布阵辅修支撑多种玩家路线。
- 同时支持 OneBot V11 与 QQ 官方适配器，并让领域规则不依赖平台 SDK。
- 覆盖修炼、战斗、社交、经济、常驻经营、特色玩法、管理和 Web 运维能力。
- 让资产变化具备明确事务、幂等键、审计记录和可恢复的失败语义。
- 以新设计为唯一产品依据；旧项目只用于识别历史风险和可选参考信息。

上游公开玩法文档可用于提取通用文字修仙玩法；上游魔改适配器可作为 OneBot V11、
QQ 官方适配器、消息投递和路由兼容层的复用来源。具体边界见
`docs/reference-sources.md`，适配器设计见 `docs/extensions/adapters/`。

## 文档入口

| 文档 | 内容 |
|:--|:--|
| [修仙 3 文档索引](docs/index.md) | 全部基础、玩法、扩展和工程文档入口 |
| [开发文档总入口](docs/development-guide.md) | 阅读顺序、文档职责、切片交付和验证门槛 |
| [完整内容开发总表](docs/content-development.md) | 首版 MVP、全部境界、功能路线、稳定键依赖和切片验收唯一权威 |
| [当前开发状态](docs/current-status.md) | 当前已开放、锁定范围和下一步顺序的唯一入口 |
| [修仙 3 总设计](docs/xiuxian3-design.md) | 世界观、境界、道途、辅修、数值和首版范围 |
| [目标架构](docs/architecture.md) | 模块边界、依赖方向和启动生命周期 |
| [适配器与 Web](docs/adapters-and-web.md) | OneBot/QQ 消息归一化、Web API 与权限 |
| [运行与安全](docs/operations.md) | 配置、任务、备份、日志和安全边界 |
| [运行基础框架](docs/runtime-framework.md) | SQLite/WAL、寻仙问道和多适配器接入 |
| [消息与文案规范](docs/messaging-copywriting.md) | Markdown 消息、适配器降级和用户可见文案 |
| [测试策略](docs/testing.md) | 测试分层、验收门槛和回滚演练 |

## 开发约定

1. 先完成文档对应的领域用例和测试，再接入命令或 Web。
2. 业务规则只能依赖领域端口，不能直接导入 NoneBot、Flask 或 SQLite。
3. 任何灵石、修为、物品、体力、积分、称号和交易状态变化都必须经过
   一个可追踪的 operation，并支持重复请求不重复扣发。
4. 新命令、外部 URL、数据结构和规则版本都必须经过文档化设计，不从旧项目推导。
5. 运行数据、密钥、用户数据、备份和媒体缓存永远不提交到 Git。

## 参考项目

行为参考必须来自 GitHub 远端 `main` 的**独立干净克隆**。参考目录不是本仓库
的必需文件；首次使用且目录不存在时执行一次：

```bash
git clone --branch main --single-branch \
  https://github.com/liyw0205/nonebot_plugin_xiuxian_2_pmv \
  ../nonebot_plugin_xiuxian_2_pmv_upstream
```

本地克隆目录可能包含本地重构或未提交改动，严禁作为参考证据。独立目录建立后
直接复用，只校验远端 URL、分支、HEAD 和工作区；
除非明确要求刷新基线，否则不要删除或重新 clone。不能通过读取同名旧目录来
代替。新项目以干净主分支的运行时观察和本仓库文档为准，不直接复制实现文件。

## 当前仓库状态

当前以 `docs/content-development.md` 作为内容、境界和功能范围入口，以
`docs/current-status.md` 判断当前分支是否已经接入运行时，以 `docs/xiuxian3-design.md`
作为跨系统设计总纲；后续实现按总表和实施计划拆分垂直切片。完整文档按
`docs/index.md` 组织；每个阶段形成独立、可测试、可回滚的提交。
