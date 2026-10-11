# M9 一键部署验证

日期：2026-10-11
分支：`work/m9-content-data`
验证目标：独立宿主，不覆盖 `/root/xiu2`、pet 或旧 xiu3 测试目录。

## 环境与命令

- 宿主：`/tmp/xiu3-onekey-m9-20261011`
- 虚拟环境：`/tmp/xiu3-onekey-m9-20261011/.venv`
- 隔离 `HOME`：`/tmp/xiu3-deploy-home-m9-20261011`
- 端口：`18093`（`8080`、`8090` 已占用，未触碰）
- 安装入口：`bash scripts/onekey.sh install --target /tmp/xiu3-onekey-m9-20261011 --venv /tmp/xiu3-onekey-m9-20261011/.venv --source-mode auto --mirror direct --index-url https://pypi.tuna.tsinghua.edu.cn/simple`
- `auto` 从当前 checkout 准备源码；没有覆盖 Release、旧安装或运行中的服务。

安装器实际通过 `nb` 安装 QQ、OneBot V11、FastAPI、HTTPX、websockets、AIOHTTP，构建并安装插件，随后校验了 53 个 JSON 文件。

## 驱动与启动

独立 venv 的导入/配置检查结果：

- `nonebot-adapter-qq 1.7.3`
- `nonebot-adapter-onebot 2.4.6`
- QQ `BotInfo` 使用形状正确的本地占位 `id/token/secret` 解析成功；占位值未连接网络，也未复制任何 pet 凭据。

宿主 `.env` 使用 `PORT=18093`、`QQ_BOTS=[]` 启动，避免向真实 QQ 建立连接。由安装生成的 `xiu3 start` 控制链实际启动 `nb run`，等待插件加载后执行 `xiu3 status`，再执行 `xiu3 stop`。日志确认：

```text
Succeeded to load plugin "nonebot_plugin_xiuxian_3"
Loaded adapters: OneBot V11, QQ
Application startup complete.
Uvicorn running on http://0.0.0.0:18093
```

启动、停止和 JSON 校验日志均未出现 `ERROR`、`Traceback` 或 `Exception`。日志留在隔离临时目录，不纳入提交。

## 边界

本次证明了一键安装、独立宿主、插件导入、QQ/OneBot 驱动注册、JSON 解析和本地 HTTP 服务启动；没有真实 QQ/OneBot 账号、WebSocket、权限、Markdown 呈现、回调 ACK 或测试消息结论。没有运行压力测试或长时间测试，既有服务和用户数据未修改。
