# NoneBot 修仙 3

`nonebot_plugin_xiuxian_3` 是面向 NoneBot 2 的文字修仙游戏插件。正式版本为 `v0.1.39`。玩家从青石镇起步，完成引导、选择道途、修炼突破，并通过移动、探索、剧情、挂机、悬赏、生产与社交逐步深入三界。角色进度保存在 SQLite，游戏内容由宿主 `data/` 下的 JSON 提供。

QQ 官方机器人与 OneBot V11 共用游戏服务。QQ 的 Markdown、蓝字与键盘按账号能力和平台权限呈现；OneBot 使用等价文本命令。发送 `修仙帮助` 可查看启程、修炼、探索、悬赏、生活和社交分类。

## 玩法

- **启程与成长**：创建角色、选择道途、修炼突破、功法和装备。
- **世界与剧情**：移动、采集、探索、自动战斗、秘境、主线和图鉴。
- **挂机与生产**：闲居路线、派遣、炼丹炼器、灵田、居所、委托和运输。
- **交易与社交**：摆摊、求购、拍卖、灵兽、宗门、师徒、道侣和队伍。

## 快速开始

Linux/Termux 可直接安装正式 Release，无需预先下载源码。要求 Python 3.11 或更高版本；安装完成后编辑 `.env` 并启动宿主：

### Linux 一键 Release 安装

```bash
curl -fsSL https://raw.githubusercontent.com/liyw0205/nonebot_plugin_xiuxian_3/v0.1.39/scripts/onekey.sh \
  | bash -s -- install --source-mode release --mirror accelerated
${EDITOR:-vi} "$HOME/xiu3/.env"
xiu3 start
```

### Termux 一键 Release 安装

```bash
pkg update -y
pkg install -y curl
curl -fsSL https://raw.githubusercontent.com/liyw0205/nonebot_plugin_xiuxian_3/v0.1.39/scripts/onekey.sh \
  | bash -s -- install --source-mode release --mirror accelerated
termux-wake-lock
```

Termux 安装器会使用 `pkg` 准备 Python、Git 和构建工具。不要混用 Termux 与 `proot-distro`
的 Python/虚拟环境；在容器内单独执行安装流程。

Release 一键安装不需要先 clone 仓库。安装器默认使用 `$HOME/xiu3` 宿主及 `$HOME/myenv` 虚拟环境，
可通过 `--target` 和 `--venv` 指定独立路径。

### 手动获取脚本或源码安装

```bash
git clone --branch v0.1.39 --single-branch \
  https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git xiuxian3-src
cd xiuxian3-src
bash scripts/onekey.sh install --source-mode source --mirror direct
```

源码模式从指定目录安装；`xiu3 update` 只支持 Release 管理安装。更新前停止并备份宿主，
升级保留 `.env`、SQLite 和自定义 JSON，官方种子仅在指纹匹配后迁移。

### 配置与启动

宿主 `.env` 的 `COMMAND_START` 控制命令前缀。只用 OneBot 时保持 `QQ_BOTS=[]`，
在 OneBot/NapCat 客户端完成账号登录，并配置反向 WebSocket：

```text
ws://服务器地址:8080/onebot/v11/ws
```

同一个 Docker 网络中的 OneBot 可使用 `ws://xiuxian3:8080/onebot/v11/ws`。
`ONEBOT_V11_ACCESS_TOKEN` 仅在启用反向 WebSocket 鉴权时填写，且须与客户端一致。

使用 QQ 官方机器人时，在 `QQ_BOTS` 填入开放平台的 AppID、Token、Secret 和事件权限；
群消息需要 `c2c_group_at_messages`。凭据保存在宿主 `.env`。
`xiu3 login` 提供可选的官方 bot 绑定辅助，QQ Markdown 和键盘仍须具备对应平台权限。

```bash
xiu3 start
xiu3 status
xiu3 logs --lines 100
```

其他系统、已有 NoneBot 宿主、配置、备份和更新步骤见[安装指南](docs/installation.md)。

## 玩家起步

```text
开始修仙
寻仙问道
完成引导 阅读
前往 近郊
我的状态
修仙帮助 启程
```

后续按状态完成采集和生产教学，再选择道途。移动、探索、挂机和主线都在对应的状态卡或分类帮助中提供下一步入口。

## 更新、备份与排错

Release 管理安装从 latest Release 获取 `project.tar.gz`。先停止并备份宿主，再更新和启动：

```bash
xiu3 stop
cp -a "$HOME/xiu3" "$HOME/xiu3.backup"
xiu3 update
xiu3 start
```

## 其他安装方式

Windows PowerShell、Docker Compose 和已有 NoneBot 宿主也可使用正式版本。Windows 与 Docker 示例需先取得发布脚本和部署文件：

```bash
git clone --branch v0.1.39 --single-branch \
  https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git xiuxian3-src
```

Windows 在 PowerShell 中运行：

```powershell
Set-Location xiuxian3-src
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\onekey_windows.ps1 install -SourceMode release -Mirror direct
```

Docker Compose 在 Linux 主机或服务器中运行：

```bash
cd xiuxian3-src
cp -n docker/env.example docker/.env
docker compose up -d --build
docker compose logs -f xiuxian3
```

Compose 将 `./data` 用作内容与 SQLite 目录，`./runtime` 保存额外运行状态；QQ 凭据只填入 `docker/.env`。
已有宿主的 Release 接入、安装参数和 Windows 控制命令见[安装指南](docs/installation.md)。

源码模式用指定源码重新安装。启动失败时先用 `xiu3 status` 和 `xiu3 logs --lines 100` 查看原因；
连接、端口、权限和恢复步骤见[安装指南排错](docs/installation.md#排错)。

Linux/Termux 管理命令为 `xiu3 start|stop|restart|status|logs|update|login`。
卸载会删除宿主目录和其中的 SQLite，执行前先备份。

## 文档

- [当前可用能力](docs/availability.md)
- [玩家使用指南](docs/usage.md)
- [安装、配置与更新](docs/installation.md)
- [文档索引](docs/index.md)
- [运行与安全](docs/operations.md)
- [MIT 许可证](LICENSE)
