# 开发文档总入口

本文只负责回答“开发时先读什么、改哪份文档、怎样算完成”。它不复制玩法数值、
境界阈值或当前运行状态；这些内容分别由总表、领域文档和状态页负责。

## 一、四个问题，四个入口

| 要回答的问题 | 唯一入口 | 说明 |
|:--|:--|:--|
| 应该开发什么 | [完整内容开发总表](content-development.md) | 全部境界、功能域、稳定键、发布边界和完整路线 |
| 当前已经开发什么 | [当前开发状态](current-status.md) | 运行时开放、部分完成、合同、锁定和下一切片 |
| 先开发哪一条 | [实施计划](implementation-plan.md) | 依赖图、垂直切片、验收和回滚 |
| 一个领域怎么实现 | 对应领域的 `README.md`、`model.md`、`workflow.md`、`use-cases.md` | 实体、状态机、应用契约和领域验收 |

不要从 `content-v*.md` 判断当前是否开放，也不要从命令处理器、旧项目或顶层兼容页
补全规则。`content-v*.md` 只用于复现历史发布快照。

## 二、文档职责

| 文档 | 只负责什么 | 不负责什么 |
|:--|:--|:--|
| `xiuxian3-design.md` | 世界观、跨系统设计原则和长期产品边界 | 当前运行状态、单个领域的实现细节 |
| `content-development.md` | 全部内容、境界、稳定键、开放边界和依赖 | 本分支已经接入的判断 |
| `current-status.md` | 当前可运行能力、端到端缺口和下一切片 | 重新定义玩法数值 |
| `implementation-plan.md` | 工程依赖、切片顺序、验收和回滚 | 复制完整功能矩阵 |
| `content-development-contract.md` | 版本、事务、随机、失败、幂等、发布和迁移合同 | 某个域的业务流程 |
| `foundation/`、`gameplay/`、`extensions/` | 领域模型、流程、用例和域内验收 | 全局开发顺序 |
| `static-data-inventory.md` | `data/` 静态配置键和字段盘点 | 运行时资产流水或玩家存档 |
| `architecture.md`、`runtime-framework.md` | 模块边界、生命周期和基础设施 | 玩法内容 |
| `messaging-copywriting.md` | QQ/OneBot 投递能力和中文文案 | 业务结算和权限判断 |
| `testing.md`、`operations.md` | 测试、备份、观测和运行手册 | 产品规则 |

### 2.1 当前配置与运行状态的边界

运行时内容包和开发状态是两条不同的轴，不能互相替代：

| 需要判断的事实 | 读取位置 | 判断方式 |
|:--|:--|:--|
| 稳定键、境界和完整功能范围 | `content-development.md` | 以总表的定义、依赖和首版边界为准 |
| 静态配置是否存在、引用是否闭合 | `data/内容清单.json`、`static-data-inventory.md` | 只读加载配置；`active/open` 表示已注册，不代表玩家可执行 |
| 当前命令或 Web 入口是否可用 | `current-status.md` | 只有 `open` 能新增玩家入口；`partial` 不能把测试夹具当成入口 |
| 本条切片的实体、流程和结算 | 对应域的 `README.md`、`model.md`、`workflow.md`、`use-cases.md` | 领域文档覆盖实现细节，不在命令层补规则 |
| 某次历史发布的参数 | 对应域的 `content-v0.*.md` | 仅用于回放/迁移/发布复原，不作为当前状态 |

因此，新增内容时先登记稳定键，再决定是否进入静态包，最后由当前状态页决定是否接入
运行时。配置包可以提前登记未来境界或天劫敌人，但在状态页为 `locked`、`contract` 或
`partial` 时，命令、按钮和 Web 写入口必须拒绝创建会话且不得扣除资产。

## 三、开始一条开发切片

按以下顺序处理，每一步都要能在提交中找到对应文件：

1. 读 `current-status.md`，确认功能不是 `partial`、`locked`、`contract` 或 `planned`，并记录现有前置。
2. 读 `content-development.md`，确定稳定键、内容版本、规则版本、成本、产出和关闭语义。
3. 进入对应领域目录，阅读 `README.md`、`model.md`、`workflow.md`、`use-cases.md`。
4. 先补领域规则和应用测试，再实现 repository、迁移和 operation ledger。
5. 接入统一 application 用例；文本、按钮、QQ、OneBot 和 Web 不能各写一套结算逻辑。
6. 按适配器能力发送结果：QQ 优先 Markdown，OneBot 支持普通消息/合并转发；降级不能回滚业务事务。
7. 补齐重复请求、并发冲突、随机回放、超时/取消、异常回滚、恢复和双适配器验收。
8. 更新当前状态和对应领域文档，最后执行本页的文档与工程门槛。

## 四、切片交付清单

每条垂直切片必须同时说明：

- 入口、权限、适配器降级和用户可见文案。
- 实体字段、不变量、状态机、错误码和并发锁。
- 前置、成本、产出、随机池、冷却/配额、失败/取消/过期。
- application DTO、Unit of Work、`operation_id` 幂等和不同输入冲突。
- 迁移、唯一约束、资产流水、备份恢复和关闭新建语义。
- 稳定键、`content_version`、`rule_version`、引用闭合和回滚步骤。
- 领域、应用、适配器、并发、回放和故障测试。
- `request_id`、`operation_id`、角色、功能、版本、结果、耗时和错误观测字段。

战斗切片还必须遵守自动回合合同：服务端依据开始快照自动选择行动、技能和目标；客户端
不得提交攻击、防御、技能、目标、伤害或结算结果。PVE 支持单人和多人协作，PvP 支持
`1v1` 与 `N v M`，未满足角色、属性、装备、技能、队伍、恢复和回放前置时只能维护合同，
不得创建运行时会话。

## 五、状态怎么判定

| 状态 | 含义 | 开发约束 |
|:--|:--|:--|
| `open` | 有完整用例、持久化、幂等和适配器测试，可供玩家使用 | 可以新增入口 |
| `partial` | 有部分状态机或生产者，但玩家路径尚未闭合 | 不能新增为玩家入口 |
| `contract` | 规则、稳定键和夹具齐全，尚未接入运行时 | 只能补基础设施和契约测试 |
| `locked` | 已登记但前置或依赖未满足 | 统一返回未开放，不扣资源 |
| `planned` | 仅列入路线，规则尚未闭合 | 不创建会话或资产结果 |

`content-v0.1` 至 `content-v0.6` 中的 `open` 只表示历史发布快照曾计划开放；当前状态
必须以 `current-status.md` 为准。

## 六、提交前验证

在修改玩法、内容或本目录入口后，至少执行：

```bash
/data/user/0/com.termux/files/home/myenv/bin/python -m pytest -q
/data/user/0/com.termux/files/home/myenv/bin/python -m pytest -q test/test_documentation.py
/data/user/0/com.termux/files/home/myenv/bin/python -m compileall -q nonebot_plugin_xiuxian_3
find data -name '*.json' -print0 | xargs -0 -n1 /data/user/0/com.termux/files/home/myenv/bin/python -m json.tool >/dev/null
git diff --check
```

文档改动还要检查：入口链接没有断链、总表/状态页/领域 README 的职责没有重复、历史
快照没有被写成当前运行状态。一个提交尽量只包含一条可回滚的垂直切片或一个基础设施能力。

## 七、历史兼容页

`docs/foundation-*.md`、`docs/gameplay-*.md` 和 `docs/extension-*.md` 为旧链接保留的
概览页。它们不再定义规则、开放状态或开发顺序；实现前请从[文档索引](index.md)进入
对应目录的 README。需要查看历史参数时，才进入对应域的 `content-v*.md`。
