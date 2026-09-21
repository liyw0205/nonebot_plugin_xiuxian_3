# 版本内容开发合同

本合同适用于 `docs/**/content-v0.1.md` 至 `content-v0.6.md` 的历史发布快照。
完整的境界、功能和开发边界以[完整内容开发总表](content-development.md)为唯一
权威；快照只用于还原某个 `content_version` 的稳定键和参数，不能另行定义玩法，
也不能要求代码按 v0.1 到 v0.6 顺序开发。

裁决顺序为：完整内容开发总表 > 本合同 > 对应领域的
`model.md`/`workflow.md`/`use-cases.md` > `content-v*.md` 历史快照 > 总设计。
快照与总表不一致时，先修总表，再生成新的快照；命令层不得复制任何内容规则。

## 1. 版本与发布语义

`content_version` 是运行时兼容和历史结算边界，不是开发里程碑。功能按垂直切片
交付：一条切片可以跨越多个内容版本，只要引用已经冻结、测试和回滚齐全。首版
（MVP-1）只执行凡人、感气、聚气、筑基十层及其基础玩法闭环；金丹以上只注册
`placeholder`/`locked` 定义，具体范围见[完整内容开发总表](content-development.md)。

| 发布版本 | `content_version` | `rule_version` | 正式开放公共境界 | 世界边界 |
|:--|:--|:--|:--|:--|
| v0.1 | `content-0.1` | `rules-0.1` | 凡人、感气、聚气、筑基 | 玄天界新手区与雾隐洞天一层 |
| v0.2 | `content-0.2` | `rules-0.2` | 金丹 | 玄天界中层、雾隐洞天二层、魔界引导 |
| v0.3 | `content-0.3` | `rules-0.3` | 元婴 | 魔界/妖界主线、跨界秘境 |
| v0.4 | `content-0.4` | `rules-0.4` | 化神 | 领域前线、远古洞天、三界深层 |
| v0.5 | `content-0.5` | `rules-0.5` | 炼虚 | 虚空航道与跨服内容 |
| v0.6 | `content-0.6` | `rules-0.6` | 合道、渡劫、飞升候选 | 终局试炼、道统与飞升/留界 |

版本升级只能新增稳定键、提高显式版本或把内容标为 `closed`；不得改写已结算 operation 的输入快照、结果、奖励或随机结果。内容关闭只拒绝新建会话；已启动的行动、订单、战斗、生产与领奖按其原 `content_version` 结算。

## 2. 通用内容对象字段

每个可执行内容定义都必须能展开为下列字段。表中未出现的字段必须采用对应领域默认值，不能由命令层猜测。

| 字段 | 要求 |
|:--|:--|
| `key` | 全局稳定 ASCII 键，例如 `location.xuantian.new_town`、`skill.body.heavy_strike`；发布后不复用 |
| `display_name` | 可本地化展示名，不作为持久化外键 |
| `content_version` / `rule_version` | 使用上表版本；结算写入 operation 快照 |
| `status` | `open`、`locked`、`closed`、`placeholder`；`placeholder` 只可展示条件，不能产生资产结果 |
| `requirements` | 境界、阶段、地点、任务、声望、道途、物品、队伍/时间条件的 AND/OR 表达式 |
| `cost` | 资源/物品/时间/耐久/次数；预检查失败时全部为零变化 |
| `output` | 资产、状态、会话、导航或展示结果；资产输出必须有可审计来源键 |
| `cooldown_or_quota` | 时长、日/周/轮次次数和作用域（角色/队伍/地点/全服） |
| `random_pool` | 需要随机时的池键、权重、保底、种子或实际抽取结果；不随机时标为 `none` |
| `failure` | 失败状态、损失、补偿、可重试条件和错误码 |
| `operation_scope` | 写动作必须提供 `operation_id`；相同 ID + 相同输入回放，相同 ID + 不同输入冲突 |
| `permissions` | `player`、`sect_role`、`admin`、`superuser` 或 Web permission；默认拒绝 |
| `observability` | `request_id`、`operation_id`、actor、scene、feature、content/rule version、结果和耗时 |
| `rollback` | 新建内容关闭方式、未结算会话处理、需要恢复的快照和不可逆边界 |

## 3. 统一事务、错误与结算

1. 所有灵石、修为、体力、精力、物品、耐久、声望、贡献、排行榜积分、资质、道途状态和奖励包变化都在一个 Unit of Work 内写入 operation ledger 与相应流水。
2. 读取、预览和帮助不创建资产 operation；它们可以记录 request 指标，但不能因渲染或媒体失败改写数据。
3. 写操作先固定内容快照、规则版本、成本和随机池；再预检查；通过后锁定/扣除、结算输出、完成 operation。任一步异常回滚，除非文档明确为可恢复会话。
4. 通用错误码：`CONTENT_NOT_FOUND`、`CONTENT_CLOSED`、`REQUIREMENT_MISSING`、`RESOURCE_INSUFFICIENT`、`COOLDOWN_ACTIVE`、`QUOTA_EXHAUSTED`、`STATE_CONFLICT`、`OPERATION_CONFLICT`、`OPERATION_IN_PROGRESS`、`PERMISSION_DENIED`、`SETTLEMENT_FAILED`。
5. 随机结算保存 `random_pool_key`、池版本、输入摘要和实际结果；重试只能返回保存结果，不能重新抽取。

## 4. 内容域默认合同

| 域 | 默认会话/结算 | 特有约束 |
|:--|:--|:--|
| `foundation/player` | 角色阶段、资质与奖励 operation | `new_user` 无资产；资质不可覆盖；暂停可读不可写 |
| `foundation/progression` | 修炼/突破 operation | 修为非负；突破失败不降境界；状态和保留比例按版本快照 |
| `foundation/paths` | 选择/切换/技能 operation | 一个首要道途；`support` 必须有主辅修；切换先计划再确认 |
| `foundation/stats` | 只读 preview 或冻结快照 | 定点整数，万分比；快照不可变；软/硬上限须解释 |
| `foundation/items` | 背包、装备、消耗/奖励 operation | 数量非负、唯一实例/绑定/耐久同事务校验 |
| `gameplay/world` | 移动会话 | 入口拒绝不扣费用；关闭地点不删除在场玩家 |
| `gameplay/exploration` | 探索会话 | 开始时锁定地点、成本和随机池；取消/过期按阶段结算 |
| `gameplay/combat` | 战斗快照/行动序列 | 回合与奖励可回放；失败不重复掉落；PVP 默认需匹配隔离 |
| `gameplay/production` | 生产订单 | 材料、精力、工具耐久和配方版本同时快照；失败返还按配方定义 |
| `gameplay/social` | 邀请、队伍、宗门/关系状态机 | 双方确认、成员上限和权限必须在同一事务验证 |
| `gameplay/economy` | 钱包、订单与锁定资产 | 先锁定后成交/取消/过期；不得出现负余额或悬挂物品 |
| `gameplay/events` | 事件轮次、任务、领奖 operation | 奖励以轮次和角色为唯一维度；过期规则明确且可重放 |
| `extensions/adapters` | 事件去重与发送结果 | 不得把 SDK/Event 传给 domain；能力不足只降级呈现 |
| `extensions/web` | 会话、CSRF、管理操作 | 写路由需权限、CSRF、Idempotency-Key 与审计原因 |
| `gameplay/livelihood` | 洞府、委托、商贸与地方建设会话 | 常驻产出受库存、订单、维护和日/周配额限制；不得直接无限生成修为 |
| `extensions/content` | 包校验/发布/回滚 | 先 lint、dry-run、依赖与引用闭合，再原子激活版本 |

## 5. 首版默认时间与限额

除非某个内容条目明确覆盖，v0.1 采用以下默认值：

| 项目 | 默认值 |
|:--|:--|
| 所有冷却/配额时区 | `XIUXIAN3_TIMEZONE`；默认 UTC，按业务日结算 |
| 角色体力/精力恢复 | 每 30 分钟各恢复 1；上限由内容包定义，v0.1 为 30 |
| 普通写 operation 幂等保留 | 至少 30 天；资产/管理/赛季 operation 永久保留或随备份保存 |
| 行动锁等待 | 5 秒；超时返回可重试 `STATE_CONFLICT`，不静默重试扣费 |
| 可取消会话 | 仅内容状态机标注 `cancellable` 的阶段；取消结果同样幂等 |
| 发送/外部调用 | 连接 5 秒、总超时 15 秒、单响应正文上限 8 MiB；核心资产不依赖其成功 |
| 内容发布 | 先 dry-run，再备份，再激活；失败回到上一 `content_version`，不重算历史 |

## 6. 开发顺序与发布版本分离

内容版本表描述“何时对玩家开放哪些稳定键”，工程计划描述“先实现哪些风险最低、
可独立验收的能力”。例如，适配器投递、operation 幂等、内容加载器和低阶战斗可以
在同一垂直切片内一起完成，不必等待整个 v0.1 的所有生产、社交和运营条目；金丹
规则也可以先完成领域测试和数据 schema，但在 `content-0.2` 激活前必须保持
`locked`。任何提前开发的功能都不能通过隐藏命令、管理员按钮或未登记的稳定键绕过
发布状态。

## 7. 开发验收模板

实现某条内容前，测试最少覆盖：内容存在/关闭、所有前置条件、资源不足、配额/冷却、状态冲突、成功、重复 operation、不同输入冲突、随机重放（如有）、持久化异常回滚、文本/按钮同一用例，以及该域列出的特有失败路径。新增或修改稳定键时，先更新 `docs/content-development.md`，再同步对应 `content-v*.md` 发布快照和引用校验；快照不能反向覆盖总表。
