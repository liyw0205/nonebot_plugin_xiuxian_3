# 发布分发约定

本仓库的普通用户入口以 GitHub Release 为准，开发者入口仍是显式源码模式。两者都使用同一套宿主模板和数据保护规则。

## Tag 与资产

- 稳定发布 tag 固定为 `vMAJOR.MINOR.PATCH`。
- Release 资产名固定为 `project.tar.gz`，必须是可列目录的 gzip tar 包。
- `.github/workflows/release.yml` 在质量检查和隔离安装冒烟通过后构建并上传资产。
- 无版本号的安装和更新请求 `https://github.com/liyw0205/nonebot_plugin_xiuxian_3/releases/latest/download/project.tar.gz`。

本次仓库核验中 GitHub 尚未提供该 `latest` 资产，因此该 URL 当前返回 HTTP 404；这不是已发布版本的通过证据。首个 `vMAJOR.MINOR.PATCH` 标签发布后，安装器才会有可用的 Release 资产。需要在首个 Release 前安装或开发时，明确使用 `--source-mode source` 的 checkout 路径。

## 下载顺序与回退

1. 默认尝试代理包装的 `latest/download/project.tar.gz` 地址。
2. 代理下载失败、返回非成功状态或归档校验失败时，直接请求 GitHub 的同一 Release URL。
3. 直连也失败时停止并保留已有宿主、`.env`、SQLite、`data/` 和 `runtime/`；不会偷偷把 Release 安装切换成未标记的 `main` 源码。
4. 源码开发必须显式传入 `--source-mode source`，更新要求 Git 工作树干净并 fast-forward。

当前保留的加速域名均已对本仓库的 Git refs 入口做过轻量验证（HTTP 200、`application/x-git-upload-pack-advertisement`）：`gh-proxy.com`、`ghproxy.net`、`ghfast.top`、`ghproxy.vip`、`gh-proxy.org`。由于当前没有 Release，它们的资产 URL 都只能记录为“待首个 Release 验证”，不能写成已下载成功。

## 数据保护

安装器只把缺失文件复制到宿主：已有 `.env`、数据库、`data/*.json` 和 `runtime/` 保留。Release 源码缓存由安装器管理，用户应在宿主目录编辑配置和数据，不要直接修改缓存。
