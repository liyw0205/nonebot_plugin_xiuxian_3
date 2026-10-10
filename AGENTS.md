# xiu3 开发入口

本仓库的当前任务、进度、阻塞与验收证据唯一入口是
[docs/current-status.md](docs/current-status.md)；工程规则、可复用 goal 和文档裁决见
[docs/development-guide.md](docs/development-guide.md)。实施计划只保留有限里程碑，
完整玩法范围与规则继续由 `docs/content-development.md`、`docs/content-data-contract.md`
和对应领域合同裁决；长历史只作归档审计。

## 当前目标

M5、M6 首采集/QQ 能力配置及分类帮助/悬赏蓝字切片已完成并推送，基线为 `06bc711`。
M7 有限清单已完成、审查并推送，业务提交为 `579c3ab`，独立远端 SHA 核验一致。
M8 玩家交互切片已完成并普通推送 main，业务提交 `f4f4388`，29 项聚焦验证与独立远端核验通过。
当前没有下一本地开发项；等待明确新目标，不重新盘点、创建旧 goal 或扩大玩法。M7 按既有功能
冻结缺项后逐域补齐定义、引用、来源和消费者。用户已明确授权设计 xiu3 自身缺失的本地来源、配方和数值；
保守复用现有规则，在 current 记录选择，不把普通配方转为等待用户逐项给数值。
必须证明 loader → 公开取得 → application/repository → 玩法消费，保留快照、事务、幂等和恢复。
未来刻意锁定效果、真实平台、支付和跨服单列；不部署、不改 xiu2，不删除必需功能或注入背包冒充来源。
QQ 回复按 AppID 能力使用 Markdown 或纯文本；M8 接通普通 handler 的按需键盘与配置前缀，
帮助不附按钮网格，待填参数使用蓝字预填，完整动作才直接发送；同一入口不重复堆叠。
不得宣称 QQ 真机呈现、权限或按钮回调已验。
共享业务使用 OneBot 代表链一次，QQ 仅受影响短合同；不重复完整成长/全量/仿真，不压测或并行长测。
适配器来源以实际运行时为准：xiu3 通过外部 pip/NoneBot CLI 使用 QQ 与 OneBot，仓内没有
SDK vendor；兄弟 `nonebot_plugin_xiuxian_2` 的 vendor 只可在明确授权后作为 patch source。
固定 SHA、候选补丁、魔改冲突和短合同见 `docs/adapter-upstream-review.md`；未核实补丁不得合并。
完成有限改动、聚焦验证、审查、普通提交并推送当前项目分支后结束；不部署、不向真实 QQ 发消息。

## 工作边界

使用 `/root/myenv/bin/python`；M8 只跑帮助、角色/生产呈现、QQ Markdown/蓝字/按钮/前缀/降级及受影响 handler 短测。
真实失败先诊断并在有限当前范围最小修复；不得 skip/ignore、删除行为断言或降低阈值求通过。
用户已授权有限数据补全、必要合同更新、审查、精确提交和普通 push main；不发版、不 force，不超出冻结清单。
按明确文件清单 stage，不纳入用户数据、运行库、密钥、日志或缓存；保护既有改动。
缓存清理只处理当前任务确认归属产物；保护 `/tmp/codex-daemon-*`、活跃 agent 目录、
IPC、socket 和 lock，禁止通配符清空 `/tmp`。
