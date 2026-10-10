# 适配器上游移植审查

审查日期：2026-10-10。本文是只读核对结果，不代表已升级依赖、覆盖源码或合并上游分支。
官方上游查询和 tarball 均放在隔离临时目录
`/tmp/xiuxian3-adapter-upstream-20261010.M5Gn3E`，不属于提交内容。

## 1. 实际加载路径

在 `/root/myenv/bin/python` 中通过 `importlib.metadata`、`importlib.import_module` 和模块
`__file__` 实测：

| 能力 | 实际分发包/版本 | 实际模块路径 | 当前仓库关系 |
|:--|:--|:--|:--|
| NoneBot | `nonebot2 2.5.0` | `/root/myenv/lib/python3.11/site-packages/nonebot/__init__.py` | 外部 pip |
| QQ | `nonebot-adapter-qq 1.7.1` | `/root/myenv/lib/python3.11/site-packages/nonebot/adapters/qq/__init__.py` | 外部 pip |
| OneBot V11 | `nonebot-adapter-onebot 2.4.6` | `/root/myenv/lib/python3.11/site-packages/nonebot/adapters/onebot/v11/__init__.py` | 外部 pip |

项目自身的 `pyproject.toml` 只声明 `nonebot2>=2.4`；`scripts/install.sh` 再通过
NoneBot CLI 的 `nb adapter install QQ` 与 `nb adapter install OneBot V11` 安装这两个
外部适配器，未在 xiu3 包内固定其源码。上述分发的 `direct_url.json` 均不存在；当前仓库没有 `vendor/`、`UPSTREAM` 或
`nonebot/adapters/*` 镜像目录。`nonebot_plugin_xiuxian_3/adapters/qq.py`、
`onebot.py`、`events.py` 和 `adapters/message/*` 是 xiu3 自写的薄归一化/投递包装，
不是上游 SDK 的复制品。`plugin.py` 加载 `adapters.nonebot.install`；该入口将 SDK 事件
归一化成 `CommandContext` 后交给共享 `AdapterRegistry -> CommandRouter -> application`。

兄弟目录 `/home/nonebot_plugin_xiuxian_2_pmv` 另有
`nonebot_plugin_xiuxian_2/xiuxian/xiuxian_adapter/vendor/` 和两个 `UPSTREAM` 文件，
但它与本仓库无关、没有被当前解释器导入，也不是 xiu3 的内置实现；只能在明确授权
后作为候选 patch source，不能称为 xiu3 的运行时来源。

## 2. 上游基线和来源

官方仓库均为 MIT 许可证：

- QQ：`https://github.com/nonebot/adapter-qq`。pip 1.7.1 对应 tag commit
  `b06e63bcf83253986194410051545512b7065033`。兄弟项目 `UPSTREAM` 记录的移植基线为
  master commit `1cdc342babde46570711eea93f8c6c41ae1bfb4f`，版本仍标为 1.7.1；该提交
  是 #216 “Guard GroupAtMessageCreateEvent from producing empty message”。
- OneBot：`https://github.com/nonebot/adapter-onebot`。兄弟项目 `UPSTREAM` 记录的
  master commit 为 `6fe01137868375afdb73a1c31e0c72dee1249703`，版本标为 2.4.6。
  官方 v2.4.6 tag 的 commit 是 `7194dbb9d363d152230ecb9a7225125999a0e6af`；当前 pip
  2.4.6 与该 tag 源码一致。两者 SHA 不同是“master 记录/版本标签”口径差异，不能合并
  写成同一提交。

审查使用的上游比较基线和文件 SHA 已保留在隔离目录；未把网络 HEAD 或未来提交当作
当前已安装版本。上游当前 master 相对 QQ v1.7.1 还包含网关读超时、非 dict DISPATCH
保护、引用索引匹配、群提及清理、QQ 群成员事件/权限及键盘 modal 等变化；OneBot 的
v2.4.6 之后比较结果主要是类型标注、导出顺序、任务集合/关闭管理等工程变化。它们是
候选补丁，不是已移植或已验收的 xiu3 修复。

## 3. 魔改差异与已知状态

兄弟项目 vendor 的 QQ `UPSTREAM` 明确记录：保留 `bot.py` 的 REFIDX/msg_idx、自动
`message_reference`、stream/prompt keyboard/action button；`event.py` 的 C2C/group
openid 缺失回退；`models/qq.py` 的可选作者/场景与扩展返回；`config.py` 的
`Intents.group_members=True`，并已合入 #216。OneBot vendor 记录 local changes none。

这些是兄弟项目的第三方移植记录，不是当前 xiu3 的运行时事实。当前 xiu3 自写层已实际
覆盖的边界是：QQ/OneBot 消息事件身份和场景归一化、稳定事件 operation key、未知场景
不可写、QQ Markdown/keyboard、OneBot 纯文本降级与 forward，以及发送失败后的去重释放。
当前层没有证据表明已实现 SDK 内部的 QQ REFIDX 解析、`msg_seq` 自动重试、interaction
ACK 生命周期、群成员 intent 或 #216 的 SDK 空消息保护；这些必须作为接入层候选补丁
单独评估，不能由共享业务成长测试代替。

当前 pip QQ 源码与 tag v1.7.1 对齐，实测不包含后续 #216；因此“#216 已移植”只能
归属于兄弟项目 vendor 记录，不能写成 xiu3 已移植。当前 xiu3 的 `extract_plaintext`
对空消息返回空字符串属于包装层行为，不等价于 SDK 的事件消息保护。

## 4. 可移植补丁清单

| 候选 | 适用层 | 当前状态 | 移植动作/风险 |
|:--|:--|:--|:--|
| QQ #216 空 `GroupAtMessageCreateEvent` 保护 | SDK QQ `bot.py` | xiu3 未证明已移植 | 只在确认加载 vendor 或升级 pip 后移植；补 SDK event fixture，保留 xiu3 normalizer 合同 |
| QQ REFIDX/msg_idx 引用匹配与 `msg_ref_id` | SDK QQ `bot.py` | 兄弟 vendor 有；xiu3 包装层只读取 reference 字段 | 作为发送/引用短合同移植；不能把业务 operation ID 当平台 msg_idx |
| QQ 网关 read timeout `Timeout(connect=30, read=None, close=30)` | SDK QQ `adapter.py` | 当前 pip 仍为 v1.7.1 基线 | 若启用 websocket，按 SDK 版本整体移植并补连接合同；不零散拷贝文件 |
| QQ 非 dict DISPATCH payload 保护 | SDK QQ `adapter.py` | 后续 master 候选 | 先补 payload fixture 和错误映射；未知事件不能进入共享写路径 |
| OneBot v2.4.6 后的任务关闭/集合管理 | SDK OneBot `v11/adapter.py` | 当前已安装 v2.4.6 tag，后续候选未移植 | 只有实际运行环境需要时按完整 commit 移植；补 initialize/close 短合同 |
| QQ 群成员/键盘 modal/权限模型 | SDK QQ event/models/config/permission | 兄弟 vendor 有部分；xiu3 未接入对应业务 | 保留 xiu3 `CommandContext` 边界，先确认产品合同和 intent，再做平台专项；不扩业务入口 |

## 5. 三方移植方法

1. **纯上游修复**：在隔离目录固定上游 tag/commit，保留 LICENSE；逐 commit 应用到
   明确的 vendored 命名空间，记录原 SHA、补丁 SHA、依赖约束和回归结果。不得直接修改
   site-packages，也不得只复制一个看似相关的文件。
2. **与魔改冲突**：先做三方 diff（共同祖先、当前 vendor、目标上游）。REFIDX 及
   SDK event fallback 是兄弟 xiuxian vendor 的既有魔改，不是 xiu3 当前包装层合同；
   若取得明确授权引入该 vendor，再按语义保留这些魔改，同时保留 xiu3 的能力降级和
   共享 DTO 边界，之后应用上游安全修复。冲突不能靠“以上游为准”解决；每个冲突列出
   保留行为和对应短合同。
3. **本地魔改保留**：只保留有明确合同和测试的差异；为每项写 `local changes`、
   维护者、来源和删除条件。上游修复若改变事件字段或生命周期，先更新归一化映射和
   适配器短合同，再判断是否影响共享 application。未确定的差异标记 `candidate`，不
   宣称已修复。

## 6. 测试合同与证据边界

由于 runtime 共用 router/application/repository，共享业务完整成长链只验一份。适配器
短合同按差异选择：

- QQ：官方 SDK 事件解析、C2C/group/channel 场景、mention/引用 REFIDX、空消息、
  interaction ACK/msg_seq、Markdown/keyboard 与发送失败重试。
- OneBot：V11 group/private 事件、消息段/forward、API timeout/重连、事件去重和
  application 接线。
- 两端共同：`CommandContext` 字段、operation key 隔离、未知场景只读、retryable 错误
  不重复业务写入。已有 `test/test_adapter_normalization.py`、
  `test/test_adapter_simulation.py` 与 `test/test_messaging.py` 提供当前短合同基础。

本轮父线程已验证 documentation、adapter normalization、messaging 全文件和两个 SDK
事件到 shared application 短节点：26 passed in 8.09s；成长模块 collect-only
收集 3 tests in 4.23s。当前旧双平台全量是实际运行证据；最终成长测试只做等价去重（
函数改名、删除重复 OneBot 迭代），229/229 行为断言、夹具、命令和结局均保留，旧 SHA
`5310dcad76623a1c8a77d869f0fb3742ed4f4e1b6fb3dd3c5f45d10496f80adb`、新 SHA
`a07095aa322c2ed887701686d6eea9c372959825833036891cda1248853d2af4`。这不是最终测试树
重新跑过全量或完整成长；真实 QQ/OneBot 账号、ACK、网络网关仍属于 B2 待验。

## 7. 结论

当前没有可直接覆盖进 xiu3 的内置 SDK 源码。下一次若要采用 vendor，应先决定“完整
外部 SDK + 独立 xiu3 包装”还是“隔离 vendor + 明确选择器”，再按本报告三方流程执行。
本轮只完成证据核对和报告，没有升级依赖、改变运行库、改写用户数据或启动新的完整成长。
