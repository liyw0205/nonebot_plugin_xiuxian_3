# v0.9 道历与运营循环内容基线（道号与道契数据化）

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.9`，`rule_version=routine-0.9.0`。

| 系统 | 稳定键/准入 | 参数与结算 |
|:--|:--|:--|
| 道号 | `data/道历/道号.json`（kind `honor_title`，17 条） | 字段 `key`/`label`/`source_event`（可空）/`hint`/`status`；顺序即 `佩戴称号 <序号>` 与功业录展示顺序 |
| 道号来源 | 12 条由 `source_event` 自动授予，5 条行卷道号 `source_event` 为空 | 自动授予沿用既有来源投影（入道、第三条问安、主线首通、派遣结算、塔层、赛季领取）；行卷道号由行卷奖励直接写入，不依赖来源事件 |
| 获取提示 | `hint` | `功业录` 对未获得的道号显示 `未获得（提示）`；已获得/已佩戴行不变 |
| 道契 | `data/道历/道契.json`（kind `dao_contract`，3 条） | 字段 `key`/`label`/`duration_days`/`price`/`daily_reward`/`activation_reward`（可选）/`reputation_every_days`/`reputation_reward`/`status` |
| 道契数值 | 日契 1 天/30 灵石/每日 30 灵石+2 精力；周契 7 天/180 灵石/每日 35+3/激活 2 张机缘签；月契 30 天/600 灵石/每日 40+4/激活 1 个道号框/每 7 日名望 3 | 价格、时长、每日与激活奖励、名望周期均与旧硬编码表逐字段一致 |

## 合同

- 定义不再写在 Python：`routine/routine_content.py` 解析并校验两份文件，
  `routine/rules.py` 由内容派生 `HONOR_TITLES` 与 `DAO_CONTRACTS`，保留同名导出与顺序；
  `honor_title()`、`dao_contract()`、`功业录`、`佩戴称号`、`我的道契`、`激活道契`、
  `领取道契` 的调用路径不变。
- 道号 `key` 必须以 `title.` 开头且唯一；`label`、`hint` 非空；`source_event` 为空或非空字符串。
- 道契 `key` 必须以 `dao_contract.` 开头且唯一；`duration_days` 为正整数、`price` 为非负整数；
  `daily_reward` 非空、`activation_reward` 可省略；奖励键非空、数量为正整数；
  声明 `reputation_reward` 时必须同时声明 `reputation_every_days`。
- `status` 只接受 `active`/`open`/`closed`/`locked`/`planned`：前两者可用；`closed` 保留在表中
  作为占位（道号已获得保留、不再自动授予，仍可佩戴；道契不可新激活，返回 `CONTENT_CLOSED`，
  已激活权益的领取不受影响）；`locked`/`planned` 只登记不入表；未知状态与空表整域拒绝。
- 两份文件必须登记 `data/内容清单.json`；清单本身变更按官方种子迁移登记新旧 SHA-256 与
  Git provenance，自定义/未知种子保留、冲突回退。

## 边界

不新增道号或道契条目、不改价格/时长/奖励数值、不新增奖励类型或数据库表；七日入道目标表
（`SEVEN_DAY_GOALS`）仍为 Python 常量，不在本版范围内；不把未开放内容写成可领取条件。
