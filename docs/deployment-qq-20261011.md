# 独立 QQ 部署验证（2026-10-11）

## 当前宿主

- 宿主：`/root/xiu3-qq-test-20261011`
- 虚拟环境：`/root/xiu3-qq-test-20261011/.venv`
- 端口：`18094`
- 安装入口：当前 checkout 的 `scripts/onekey.sh`
- 源码来源：安装时使用当前包含既有未提交 M9 改动的工作树；不能把本次宿主称为只含提交 `44be521` 的纯净构建产物。
- QQ 凭据：来自既有 pet 部署配置，仅用于本地启动核对，凭据不写入本文。

## 45 秒探测证据

控制端曾启动并主动停止一次短探测，日志为 `/tmp/xiu3-deployment-20261011/startup.log`。日志确认：

- `nonebot_plugin_xiuxian_3` 成功加载。
- OneBot V11 与 QQ 适配器成功注册。
- Uvicorn 在 `127.0.0.1:18094` 启动并完成 application startup。
- QQ bot 收到 `READY`，随后有群消息事件进入 NoneBot。
- 探测完成后由控制端主动停止，未进行压力测试或长时间测试。

该证据覆盖插件导入、适配器注册、QQ READY 和本地 HTTP 启动；不替代 QQ 权限、Markdown/蓝字/按键呈现或 OneBot/NapCat 独立登录验收。

## 当前长期实例

控制端随后使用 `/root/xiu3-qq-test-20261011/xiu3 start` 启动长期实例，继续使用端口 `18094` 和同一宿主配置。长期实例的 PID、端口和 READY 状态由控制端单独核对；本文不停止、不重启该实例，也不重复发送测试消息。

## 边界

旧的 `/root/xiu3-qq-test-20261010` 与 `/tmp/xiu3-*m9-20261011` 测试目录不作为本次验证输入。未执行全量测试、压力测试、Release 下载或数据迁移；用户数据、凭据和缓存未纳入提交。
