# 发布分发约定

GitHub Release 是发布后的普通用户入口；在没有可用 Release 资产时，当前可用入口是显式 checkout `work/m9-content-data` 的源码模式。两者都使用同一套宿主模板和数据保护规则。

## Tag 与资产

- 稳定发布 tag 固定为 `vMAJOR.MINOR.PATCH`。
- Release 资产名固定为 `project.tar.gz`，必须是可列目录的 gzip tar 包。
- `.github/workflows/release.yml` 在质量检查和隔离安装冒烟通过后构建并上传资产。
- 无版本号的安装和更新请求 `https://github.com/liyw0205/nonebot_plugin_xiuxian_3/releases/latest/download/project.tar.gz`。

当前 GitHub `latest` 资产 URL 返回 HTTP 404，因此现在应先 checkout `work/m9-content-data` 并使用 `--source-mode source`；不能把未发布的 Release 写成可安装版本。发布首个 `vMAJOR.MINOR.PATCH` 并上传资产后，再切换到 Release 段落中的命令。

## 下载顺序与回退

1. 默认尝试代理包装的 `latest/download/project.tar.gz` 地址。
2. 代理下载失败、返回非成功状态或归档校验失败时，直接请求 GitHub 的同一 Release URL。
3. 直连也失败时停止并保留已有宿主、`.env`、SQLite、`data/` 和 `runtime/`；不会偷偷把 Release 安装切换成未标记的 `main` 源码。
4. 源码模式必须显式传入 `--source-mode source`，当前分支更新应先 `git -C <src> pull --ff-only origin work/m9-content-data`，再执行 `bash <src>/scripts/install.sh update <host> --venv <venv>`；不要使用会跟踪 `origin main` 的 `xiu3 update`。

当前保留的加速域名均已对本仓库的 Git refs 入口做过轻量验证（HTTP 200、`application/x-git-upload-pack-advertisement`）：`gh-proxy.com`、`ghfast.top`、`ghproxy.vip`、`gh-proxy.org`。由于当前没有 Release，它们的资产 URL 都只能记录为“待首个 Release 验证”，不能写成已下载成功。

## 数据保护

安装器只把缺失文件复制到宿主：已有 `.env`、数据库、`data/*.json` 和 `runtime/` 保留。Release 源码缓存由安装器管理，用户应在宿主目录编辑配置和数据，不要直接修改缓存。
