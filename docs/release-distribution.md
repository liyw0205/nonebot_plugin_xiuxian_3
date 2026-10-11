# 发布分发约定

`main` 是公开源码、安装和更新的唯一入口。版本化 Release 必须从 `main` 上的稳定版本 tag 构建。

源码安装显式 checkout `main` 并使用 `--source-mode source`；Release 安装使用 `main` 上的远程引导脚本和最新正式 Release 资产。两者都使用同一套宿主模板和数据保护规则。

## Tag 与资产

- 稳定发布 tag 固定为 `vMAJOR.MINOR.PATCH`。
- Release 资产名固定为 `project.tar.gz`，必须是可列目录的 gzip tar 包。
- `.github/workflows/release.yml` 在质量检查和隔离安装冒烟通过后构建并上传资产。
- 无版本号的安装和更新请求 `https://github.com/liyw0205/nonebot_plugin_xiuxian_3/releases/latest/download/project.tar.gz`。

Release 管理宿主的日常更新顺序是停止、备份、执行 `xiu3 update`、重新启动。更新命令下载 latest `project.tar.gz`，更新程序文件而保留宿主 `.env`、SQLite、`data/`、`runtime/` 和 venv。

## 下载顺序与回退

1. 默认尝试代理包装的 `latest/download/project.tar.gz` 地址。
2. 代理下载失败、返回非成功状态或归档校验失败时，直接请求 GitHub 的同一 Release URL。
3. 直连也失败时停止并保留已有宿主、`.env`、SQLite、`data/` 和 `runtime/`；不会偷偷把 Release 安装切换成未标记的源码。
4. 源码模式必须显式传入 `--source-mode source`。Release 管理目录执行 `xiu3 update` 时重新下载 `latest/download/project.tar.gz`，更新脚本本身不执行 `git fetch/pull`。源码模式使用当前 checkout，不自动同步源码；它适用于首次源码安装或本地开发，不属于 Release 管理更新流程。

代理地址由安装脚本维护；代理下载或归档校验失败时会回退到 GitHub Release 直连，不会静默切换到源码安装。Release 更新只替换独立源码缓存，不覆盖宿主、`.env`、SQLite、`data/`、`runtime/` 或 venv。

## 数据保护

安装器只把缺失文件复制到宿主：已有 `.env`、数据库、`data/*.json` 和 `runtime/` 保留。Release 源码缓存由安装器管理，用户应在宿主目录编辑配置和数据，不要直接修改缓存。
