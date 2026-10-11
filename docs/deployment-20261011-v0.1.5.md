# v0.1.5 指定测试宿主迁移记录

日期：2026-10-11。仅操作 `/root/xiu3-qq-test-20261011`，用户已明确授权新 Release、受控种子更新、
两个未知 JSON 的最小人工合并及 QQ 重启。未触碰 pet/xiu2、共享 `/root/myenv`，未发送 QQ 消息，未做玩法全量或压测。

## 发布与验证

- 修复提交：`4aa182c8e07defc686f4ddf3cd500e97ebe21603`，普通推送 main，独立 ls-remote 一致。
- main CI：[38137693167](https://github.com/liyw0205/nonebot_plugin_xiuxian_3/actions/runs/38137693167)，成功。
- Release：[v0.1.5](https://github.com/liyw0205/nonebot_plugin_xiuxian_3/releases/tag/v0.1.5)。
  标签工作流 [38137940871](https://github.com/liyw0205/nonebot_plugin_xiuxian_3/actions/runs/38137940871)
  的 quality 3.11/3.12、install-smoke、release 全部成功。
- annotated tag 对象 `591c93cd4fb7f8f81c36f5323b8b8bd1e3e59971`，peeled commit 为上述修复 SHA。
  v0.1.1–v0.1.4 未移动/删除。
- API 确认 latest=v0.1.5。`project.tar.gz` 为 2356337 字节，实际经 gh-proxy.com 下载至
  `/tmp/xiu3-verified-v0.1.5.tar.gz`；SHA-256 与 API digest 一致：
  `17a540fb4f748b2d8a13b9ae50adbb8a69c2fdd68fe1510c458eb258663e0748`。
  宿主 Release 缓存的安装 helper 与该归档字节一致。
- 本地最后受影响组 13 passed in 163.27s，JUnit `/tmp/xiu3-v015-seed-final.xml`；
  bash -n、改动 Python 编译及 diff check 通过。首轮 10 passed 为先前验证，不累加为不同覆盖。
  仅使用实例自己的 Python/runtime，借用预先准备的本地 pytest 工具；测试内无 pip 下载。
  发版后未重跑种子组，仅执行真实宿主更新、加载、数据保留及启动检查。

## 备份与六项差异

宿主停止且旧进程消失后，备份 `.env`、data（53 JSON 与 SQLite/WAL/SHM）、bot.py、pyproject、
管理脚本及插件源码到 `.xiuxian3/backups/pre-v0.1.5-20261011`，目录权限 700。
此前 v0.1.4 的备份仍保留；那次更新失败不作为迁移成功证据。

四项旧文件在 Git 历史中有字节级 SHA-256 匹配，来源与固定新版指纹登记于 `scripts/seed_migrations.json`：

| 文件 | 已匹配旧官方提交 | 新版内容提交 |
|:--|:--|:--|
| 剧情/主线.json | e61e67cf180c2e3b280a160da81cef50cd685b77 | 42d17725413667a3f72fcc604c163e33c63e59e9 |
| 引导/引导.json | 42db275e70a60bbb5d268b7384d2eef44e6be80f | 9de693077677699def1ccb53150356b9ca4fee9c |
| 技能/技能.json | 42db275e70a60bbb5d268b7384d2eef44e6be80f | 3e009434e6e6ff26b65419cb13458298b9661293 |
| 道具/材料.json | 579c3ab277d90eafd9d267693be89e678b533282 | eaed7115257db5a67933e8bdf833c003319d940d |

两个文件没有 Git 历史字节或 JSON 语义等价匹配，不能伪造旧官方 provenance：

- 奖励/奖励.json 原 SHA-256：`51d361756bf647807144732278fc5f6f56b2bfd4902f65fc3c402be82c8669af`。
  只给 `reward_pool.exploration.spring_gather` 原四个 outcome 各追加 1 份 `item.food.coarse_spirit_rice`。
  原权重 3600/2400/2400/1600、其他奖励、desc 与所有其他记录保留。
- 战斗/遭遇池.json 原 SHA-256：`51db1f1b7ec092078c3a2592b9ca3099073b90959f0f9e5f4fad0ef79f9c1323`。
  按原有 14 个稳定 key 补缺失 desc，不改变候选、权重或其他字段。
- 原件在上述备份的 data 路径，差异为 `manual-rewards.diff`、`manual-encounters.diff`。
  JSON 逐字段比较确认仅以上授权变化；它们没有加入通用旧官方迁移表。

## Release 更新

旧宿主下载器会误选 Docker 子目录，因此使用已推送的修正引导脚本获取 latest 归档，
再执行归档自身的 installer；没有 fetch/pull，也未 pip 安装 xiu3。

```bash
bash /home/nonebot_plugin_xiuxian_3/scripts/onekey.sh update \
  --target /root/xiu3-qq-test-20261011 \
  --source /root/xiu3-qq-test-20261011/.xiuxian3/release-source \
  --source-mode release --mirror accelerated \
  --venv /root/xiu3-qq-test-20261011/.venv
```

更新退出码 0，日志 `/tmp/xiu3-v015-migration-update.log`。自动事务备份为
`.xiuxian3/backups/deploy-2fd189f00307460689384a5a4ac08287`；4 官方种子迁移，53 JSON 事务内语法检查与严格验载通过。
奖励文件因保留原 desc 仍与官方不同，安装器明确保留，不能声称所有宿主 JSON 都是官方原样。
部署异常会恢复本次源码/TOML/种子；依赖准备不属于版本回退，完整宿主备份保留。

启动前 `.env`、bot.py、SQLite/WAL/SHM 与备份字节一致；原 data 56 文件中仅授权 6 JSON 改变，
其余 50 不变。启动后 `.env` 仍字节一致，JSON 可解析，SQLite 只读 integrity_check=ok。
SQLite 启动后的正常 schema/WAL 生命周期不宣称字节不变；没有替换数据库或发游戏命令。

实际宿主内容校验通过：材料 12/来源 17/模式 9/配方消费者 29；
敌人 55/profile 33/遭遇池 14/候选 27/drop pool 6/消费遭遇池 12/敌人技能 11。

## 加载与启动

使用自身 `.venv/bin/python` 运行真实 bot.py 的只加载分支，不触发 server/startup，再检查 NoneBot 注册集合：

```text
module_file=/root/xiu3-qq-test-20261011/src/plugins/nonebot_plugin_xiuxian_3/__init__.py
matchers=1 handlers=1 duplicate_matchers=0
handler_module=src.plugins.nonebot_plugin_xiuxian_3.adapters.nonebot
plugin_distribution_absent=True
```

pyproject 使用 `plugin_dirs=["src/plugins"]`，旧 xiu3 `@local` 项已移除。
第一次普通后台启动未保活，日志仅到 Using python；不作为启动成功证据。
随后使用 nohup/setsid 隔离会话启动 `./xiu3 start`，未更改运行配置：

- manager PID 3480402（nb）、子 PID 3480409（bot.py），cwd 与 Python 均属于指定宿主。
- `127.0.0.1:18094` 由该 bot 子进程监听。
- `.xiuxian3/nb.log` 已出现插件从 src.plugins 加载、QQ READY、Uvicorn 和 Application startup complete；
  本次启动日志 ERROR/Traceback 均 0。实例保持运行，未因文档收口停止。
- 串行验证与启动单 CPU，虚拟内存硬上限 768 MiB；启动抽样 RSS 为 nb 65736 KiB、bot 145136 KiB。
  最后 available RAM 1229 MiB、swap used 1959 MiB；未广泛清理缓存或停止其他服务，备份及原始证据保留。

Windows/Termux 未真机执行，Docker 只证明共用迁移引擎与数据模式，没有 Docker 实机全测。
QQ READY 仅证明连接，不证明 Markdown/蓝字/按钮呈现、权限或回调；未发真实测试消息。
