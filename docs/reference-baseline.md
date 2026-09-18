# 参考基线

## 1. 参考来源

本方案依据以下远端基线整理。这里的“参考副本”是一个需要单独创建的临时
工作目录，不是新项目的一部分，也不能用同名旧目录替代：

- 远端：`git@github.com:liyw0205/nonebot_plugin_xiuxian_2_pmv.git`
- 分支：`main`
- 盘点提交：`97f43acba8dd185111d998c48d4e1cf5a069b117`
- 盘点日期：2026-09-19

在任何远程或本地环境开始盘点前，执行：

```bash
cd /home
test ! -e nonebot_plugin_xiuxian_2_pmv_upstream
git clone --branch main --single-branch \
  https://github.com/liyw0205/nonebot_plugin_xiuxian_2_pmv.git \
  nonebot_plugin_xiuxian_2_pmv_upstream
git -C nonebot_plugin_xiuxian_2_pmv_upstream status --short --branch
git -C nonebot_plugin_xiuxian_2_pmv_upstream rev-parse HEAD
```

`/home/nonebot_plugin_xiuxian_2_pmv` 是另一个工作区，可能正处于
`refactor/full-bottom-layer` 或其它未提交状态；无论它看起来是否干净，都不能
读取、执行或作为本方案的证据。若 `nonebot_plugin_xiuxian_2_pmv_upstream` 已
存在，先确认它的 remote、分支、HEAD 和 `git status`，不满足 `main` 干净条件
就删除该临时副本并重新克隆。远端还存在其它分支，但本仓库不以它们为基线。

## 2. 观察到的范围

- NoneBot 插件，支持 OneBot V11 与 QQ 官方适配器。
- 本地 SQLite 数据、JSON 资源、图片资源、APScheduler 定时任务和 Flask Web 面板。
- 约 640 条命令声明（含重复/别名语义），核心/社交/世界/经济/娱乐/管理模块
  近 40 个，测试覆盖大量交易、战斗、活动、数据库和适配器场景。
- Web 入口覆盖配置、数据库、命令、消息、活动、奖励、任务、备份、日志、更新、
  终端和 QQ 官方机器人绑定。

## 3. 证据等级

1. 运行时行为和可复现的测试结果。
2. 干净主分支中实际加载的 README、配置、模块和资源清单。
3. 帮助文案、注释和未加载文件。

如果文档、源代码和运行时冲突，先复现运行时，再记录差异；不因为某个旧类名
或目录名而把实现细节当成新项目协议。

## 4. 使用方式

开发某个功能时，先在上述独立参考副本中确认命令、参数、权限、冷却、资源、成功/失败
文案和定时边界，再把这些行为改写为新项目的领域验收样例。禁止直接复制旧
Python 模块、旧数据库文件、旧运行数据、旧图片模板或旧构建脚本。

参考副本可定期删除后重新克隆；新的盘点应在本文件增加提交号、目录校验和
变更摘要，而不是静默覆盖旧基线。任何 goal 的提示词都必须携带这条隔离要求。
