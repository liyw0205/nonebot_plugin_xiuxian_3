# xiu3 开发入口

本仓库的当前任务、进度、阻塞与验收证据唯一入口是
[docs/current-status.md](docs/current-status.md)；工程规则、可复用 goal 和文档裁决见
[docs/development-guide.md](docs/development-guide.md)。实施计划只保留有限里程碑，
完整玩法范围与规则继续由 `docs/content-development.md`、`docs/content-data-contract.md`
和对应领域合同裁决；长历史只作归档审计。

## 当前目标

M5 已完成并推送；当前 M6 只处理 current 第 4 节登记的两项有限交付：以已结算的首次
近郊采集 operation 作为 `item.manual.sunrise_breath` 的一次性引路嘉奖来源；接通
`XIUXIAN3_QQ_CAPABILITIES` 的按 AppID 声明，使实际 QQ handler 的 Markdown 能力与纯文本降级
遵循配置。普通 QQ 回复使用 Markdown segment；蓝字是 Markdown inline command，键盘是单独
keyboard segment；普通 handler 不会自动生成它们。不得宣称 QQ 真机呈现、权限或按钮回调已验。
共享 router/application/repository 的业务长链只跑一份；本轮只跑首次采集对应短合同和本地
QQ presenter/config 测试，不重复共享适配器测试或启动全量成长。
适配器来源以实际运行时为准：xiu3 通过外部 pip/NoneBot CLI 使用 QQ 与 OneBot，仓内没有
SDK vendor；兄弟 `nonebot_plugin_xiuxian_2` 的 vendor 只可在明确授权后作为 patch source。
固定 SHA、候选补丁、魔改冲突和短合同见 `docs/adapter-upstream-review.md`；未核实补丁不得合并。
完成有限改动、聚焦验证、审查、普通提交并推送当前项目分支后结束；不部署、不向真实 QQ 发消息。

## 工作边界

使用 `/root/myenv/bin/python`；M6 不启动全量或完整成长长测。
真实失败先诊断并在有限当前范围最小修复；不得 skip/ignore、删除行为断言或降低阈值求通过。
用户已授权该有限玩法及适配器配置修复、审查、提交和普通 push；不发版、不 force，不扩展到其他玩法。
按明确文件清单 stage，不纳入用户数据、运行库、密钥、日志或缓存；保护既有改动。
缓存清理只处理当前任务确认归属产物；保护 `/tmp/codex-daemon-*`、活跃 agent 目录、
IPC、socket 和 lock，禁止通配符清空 `/tmp`。
