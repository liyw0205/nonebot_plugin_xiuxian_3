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
M9 数据与受影响消费者已合入 main（`9be1cae`），CI 已通过，不重新执行 M9。
主线首两关真实切片已推送 `42d1772`；Docker 宿主源码加载修复已推送 `b79e28b`，v0.1.4 已发布。
Release 根目录识别、共享安全种子迁移和失败回退已完成并推送 `4aa182c`，v0.1.5 已发布，
quality 3.11/3.12、install-smoke/release 全部成功。指定宿主 `/root/xiu3-qq-test-20261011`
已从 Release 更新并重启，源码位于 src/plugins，1 matcher/1 handler、无 xiu3 pip 包，QQ READY。
仅此宿主的两个未知基线 JSON 按用户授权备份后最小人工合并，未伪造官方指纹。
本次发布与此宿主部署由用户明确授权，不代表其他环境投产或 QQ 消息呈现验收。
`main` 是安装/Release 分支，`develop` 是唯一活动开发分支；旧 `work/*`、`docs/*` 分支和
worktree 仅作历史保留，不删除、不盲合。M9 已结束并合入 main，不重开 M9/旧 goal。
当前有限任务在 develop 完成 `chapter.1.stage.3` 雾中守门与 `chapter.2.stage.1` 城镇委托两关，
先补正文/人物/场景/目标/来源/奖励/后续/重试数据，再接现有战斗、委托、快照、事务和幂等消费者。
M7 仅完成旧范围来源/引用修补，不作为 M9 内容完整证明。
本地内容沿用现行规则与已记录依赖；保留 loader → 公开取得 → application/repository → 玩法消费链、
快照、事务、幂等和恢复语义，不把未来 locked 内容或外部条件混入本地完成声明。
未来刻意锁定效果、真实平台、支付和跨服单列；不改 xiu2/pet，不删除必需功能或注入背包冒充来源。
QQ 回复按 AppID 能力使用 Markdown 或纯文本；M8 接通普通 handler 的按需键盘与配置前缀，
帮助不附按钮网格，待填参数使用蓝字预填，完整动作才直接发送；同一入口不重复堆叠。
不得宣称 QQ 真机呈现、权限或按钮回调已验。
共享业务使用 OneBot 代表链一次，QQ 仅受影响短合同；不重复完整成长/全量/仿真，不压测或并行长测。
适配器来源以实际运行时为准：xiu3 通过外部 pip/NoneBot CLI 使用 QQ 与 OneBot，仓内没有
SDK vendor；兄弟 `nonebot_plugin_xiuxian_2` 的 vendor 只可在明确授权后作为 patch source。
固定 SHA、候选补丁、魔改冲突和短合同见 `docs/adapter-upstream-review.md`；未核实补丁不得合并。
本轮已完成普通推送 main、新 tag/Release 和指定宿主迁移；未向 QQ 发送测试消息。

## 工作边界

本次 runtime/验载仅使用指定实例自己的 `.venv/bin/python`，不修改或使用共享 `/root/myenv`。
聚焦回归串行且资源有界；不全量、不压测，不重复已完成玩法长链；Docker 不做实机全测。
真实失败先诊断并在有限当前范围最小修复；不得 skip/ignore、删除行为断言或降低阈值求通过。
M9 与首段剧情已完成；当前仅推进上述两关，不扩 84 关、不扩 PvP/支付/跨服，不 force、不改写历史或移动旧 tag。
后续官方 data 变更须维护 `scripts/seed_migrations.json`：旧/新 SHA-256 与 Git provenance，
仅迁移确证旧官方文件，保留自定义/未知 JSON；语法/严格验载失败自动回退，见发布分发文档。
按明确文件清单 stage，不纳入用户数据、运行库、密钥、日志或缓存；保护既有改动。
缓存清理只处理当前任务确认归属产物；保护 `/tmp/codex-daemon-*`、活跃 agent 目录、
IPC、socket 和 lock，禁止通配符清空 `/tmp`。
