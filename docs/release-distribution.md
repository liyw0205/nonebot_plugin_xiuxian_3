# 发布分发约定

`main` 是公开源码、安装和更新的唯一入口。版本化 Release 必须从 `main` 上的稳定版本 tag 构建。

源码安装显式 checkout `main` 并使用 `--source-mode source`；Release 安装使用 `main` 上的远程引导脚本和最新正式 Release 资产。两者都使用同一套宿主模板和数据保护规则。

## Tag 与资产

- 稳定发布 tag 固定为 `vMAJOR.MINOR.PATCH`。
- Release 资产名固定为 `project.tar.gz`，必须是可列目录的 gzip tar 包。
- `.github/workflows/release.yml` 在质量检查和隔离安装冒烟通过后构建并上传资产。
- 无版本号的安装和更新请求 `https://github.com/liyw0205/nonebot_plugin_xiuxian_3/releases/latest/download/project.tar.gz`。

Release 管理宿主的日常更新顺序是停止、备份、执行 `xiu3 update`、重新启动。更新命令下载 latest `project.tar.gz`，更新程序文件而保留宿主 `.env`、SQLite、用户 JSON、`runtime/` 和 venv；仅已证实的旧官方种子在备份后迁移。

## 下载顺序与回退

1. 默认尝试代理包装的 `latest/download/project.tar.gz` 地址。
2. 代理下载失败、返回非成功状态或归档校验失败时，直接请求 GitHub 的同一 Release URL。
3. 直连也失败时停止并保留已有宿主、`.env`、SQLite、`data/` 和 `runtime/`；不会偷偷把 Release 安装切换成未标记的源码。
4. 源码模式必须显式传入 `--source-mode source`，仅用于首次源码安装或本地开发。`xiu3 update` 只接受 Release 管理安装，并重新下载 `latest/download/project.tar.gz`；缺少 Release 管理源码时直接失败，不使用 Python 包索引更新插件。

代理地址由安装脚本维护；代理下载或归档校验失败时会回退到 GitHub Release 直连，不会静默切换到源码安装。归档根必须同时包含根 pyproject、安装脚本及插件入口，不能误选 Docker 子目录；完整缓存准备后再原子切换。Release 更新不覆盖 `.env`、SQLite、用户自定义 JSON、`runtime/` 或 venv。

## 数据保护

Linux/Termux、Windows 和 Docker 共用 `scripts/install_plugin_source.py` 与 `scripts/seed_migrations.json`。
仅字节级 SHA-256 匹配并有 Git 来源证据的旧官方 JSON 迁移到固定新版指纹；缺失 JSON 补齐，
其余已有 JSON 保留。未知基线不能冒称旧官方数据。Release 源码缓存由安装器管理，用户在宿主编辑配置/数据。

源码、TOML 与发生替换的种子先保存在 `.xiuxian3/backups/deploy-*`（Docker 为持久 data volume 内的
`data/.xiuxian3/backups/deploy-*`），`deployment.json` 记录
pending/complete/rolled_back。事务内检查所有 JSON 语法并实际验载，失败恢复本次修改并明确报告自定义冲突；
不放宽剧情校验、不覆盖整个 data、不触碰 SQLite/.env。Docker 失败不启动新进程，恢复的 data 可由旧镜像启动；
普通宿主恢复旧插件与 TOML 后可重试/使用备份。依赖准备先于部署事务，依赖版本不自动回退，完整宿主备份仍必要。
旧 pip 发行包仅在新源码成功验载后卸载。

每次官方 data 变更必须更新旧/新指纹与 Git provenance，并保留受支持的旧指纹；
新增来源提交尚未生成时先提交数据再登记，不能填猜测 SHA。发布前运行种子迁移聚焦回归及目标指纹校验。
