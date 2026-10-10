# xiu3 开发入口

本仓库的当前任务、进度、阻塞与验收证据唯一入口是
[docs/current-status.md](docs/current-status.md)；工程规则、可复用 goal 和文档裁决见
[docs/development-guide.md](docs/development-guide.md)。实施计划只保留有限里程碑，
完整玩法范围与规则继续由 `docs/content-development.md`、`docs/content-data-contract.md`
和对应领域合同裁决；长历史只作归档审计。

## 当前目标

2026-10-10 本轮唯一目标是 current 的 M5：取得业务基线一次全量 pytest，以及
新角色公开命令成长至渡劫 L10、飞升/留界的完整本地验收；全量中的相同链可复用。
用户明确授权本次等价测试去重复用 PID 2428825 的旧双平台全量：成长节点仅改名、
删除重复 OneBot 迭代，229/229 行为断言、夹具、命令和结局不变；结构/collect 与
适配器短合同补验即可，不重新运行全量或完整成长，不称最终测试树已重新全量。
共享 router/application/repository 的业务长链以后只跑一份，两端差异保留短合同。
适配器来源以实际运行时为准：xiu3 通过外部 pip/NoneBot CLI 使用 QQ 与 OneBot，仓内没有
SDK vendor；兄弟 `nonebot_plugin_xiuxian_2` 的 vendor 只可在明确授权后作为 patch source，
不能当作 xiu3 已加载源码。固定 SHA、候选补丁、魔改冲突和短合同见
`docs/adapter-upstream-review.md`；未核实补丁不得合并或升级依赖。
复用有效安装/启动/备份恢复证据，审查本轮全部相关 code/test/docs/AGENTS，
提交并普通推送到 origin/main 成功后才可结束本轮 goal。B1–B3 规则/来源、真实平台与
外部条件仍阻断完整产品/正式发布，不能阻断已实现公开能力的本地 M5 或代替未跑测试。

## 工作边界

使用 `/root/myenv/bin/python`；本轮 M5 是必须执行的阶段验收，同一长测只有一个运行者。
真实失败先诊断并在有限当前范围最小修复；不得 skip/ignore、删除行为断言或降低阈值求通过。
用户已授权必要修复、审查、提交和普通 push；不发版、不 force，不扩新玩法。
按明确文件清单 stage，不纳入用户数据、运行库、密钥、日志或缓存；保护既有改动。
缓存清理只处理当前任务确认归属产物；保护 `/tmp/codex-daemon-*`、活跃 agent 目录、
IPC、socket 和 lock，禁止通配符清空 `/tmp`。
