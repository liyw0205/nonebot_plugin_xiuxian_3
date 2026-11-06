# v0.10 闲居与道统的玩家入口

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.10`，
`rule_version=specials-0.10.0`。本版不新增玩法系统，只补齐两条玩家入口：入道后的闲居指路引导，
以及 `修仙帮助` 中缺失的闲居与道统/据点说明。

## 1. 闲居指路引导

`data/引导/引导.json`（kind `guide`）新增 `guide.idle_entry`：

- `label`：闲居指路；`command`：`闲居`；别名 `挂机`、`闲居指路`、`挂机指路`。
- 门槛：`requirements: [{type: stage, stage: cultivator}]`，入道后可用；`cost: {}`，
  `repeatable: true`，可反复阅读。
- 输出：`{type: intro_flag, key: guide.idle_entry}`，写入 `guide.idle_entry` 旗标。
- 内容覆盖 `挂机预览`、`开始挂机`、`领取挂机`、`取消挂机` 的真实流程与 60 秒撤回、
  逾时所得边界，并说明境界、贸易许可、地方名望、宗门道统都可能是路线门槛。

引导由既有 `完成引导 <名称>` 消费，写入旗标与 operation 幂等均沿用 `player.complete_intro`；
本版不新增命令、表或字段。凡人阶段不可用该引导，避免把入道后的入口混入新手三课。

## 2. 帮助页补齐

`nonebot_plugin_xiuxian_3/xiuxian/application.py` 的 `_HELP_PAGES`：

- `生活` 在派遣段后新增闲居段：`挂机预览`、`开始挂机`、`领取挂机`、`取消挂机`，
  并写明 60 秒内可撤回。
- `社交` 在道友段后新增道统与据点段：`道统`、`道统投票`、`道统结算`、`建立据点`、`据点`。

文案只用真实命令与既有 `command_link` 蓝字，不新增按钮网格，不重复既有段落；帮助页仍为
纯文本加命令链接，QQ 与 OneBot 共用同一份文本。

## 3. 验收

`test/test_help_idle_dao.py` 覆盖：

- `修仙帮助 生活` 含四条挂机命令，`修仙帮助 社交` 含道统与据点命令；
- 帮助文本使用真实换行而非字面 `\n`；
- 入道角色 `完成引导 闲居` 成功并写入 `guide.idle_entry` 旗标，重放返回已记录；
- 凡人阶段不可完成该引导，引导进度分母不含入道后的条目。

回归：`test_intro*.py`、`test_documentation.py`、`test_idle*.py`。
