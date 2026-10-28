# v1.0 道历与运营循环内容基线（七日入道数据化）

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-1.0`，`rule_version=routine-1.0.0`。

| 系统 | 稳定键/准入 | 参数与结算 |
|:--|:--|:--|
| 七日入道 | `data/道历/七日目标.json`（kind `seven_day_goal`，7 条） | 字段 `day_number`/`key`/`label`/`hint`/`event_key`/`reward`/`local_reputation_key`/`status`；`day_number` 为 1..7 且连续唯一 |
| 目标与奖励 | D1 道历问安→灵米×1；D2 近郊采集→止血草×2；D3 生产预览→灵石30；D4 接取悬赏→名望2；D5 试炼塔一层→阵砂×2；D6 结算派遣→灵石50；D7 选择道途→名望5+机缘签×2 | 与旧硬编码表逐字段一致，奖励数值不变 |
| 来源事件 | `routine.checkin.daily`、`explore.gather_outskirts`、`production.preview`、`bounty.accept`、`specials.tower.floor.1`、`specials.dispatch.settled`、`player.enter_cultivation` | 沿用既有来源投影，不新增事件类型 |
| 获取提示 | `hint` | `七日入道` 对未完成的目标显示 `hint`；已完成/已领取行不变，`data.goals` 附带 `hint` |
| 展示与领取 | `七日入道` / `领取七日目标 <1-7>` | 日数与顺序以内容为准；领取仍按业务日、operation 回放与唯一约束结算 |

## 合同

- 定义不再写在 Python：`routine/routine_content.py::seven_day_goal_definitions()` 解析并校验文件，
  `routine/rules.py` 由内容派生 `SEVEN_DAY_GOALS`（保留同名导出与日数顺序），
  `seven_day_goal(day)`、七日进度/领取、`campaign_complete`、快照与幂等路径不变。
- `key` 必须以 `quest.seven_day.` 开头且唯一；`label`、`hint`、`event_key` 非空；`reward` 非空且
  数量为正整数；有 `local_reputation` 时必须声明可解析的 `local_reputation_key`，无该奖励时
  不得声明；日数重复或断档、未知状态、空表整域拒绝。
- `status` 只接受 `active`/`open`/`closed`/`locked`/`planned`：前两者可领取；`closed` 保留占位、
  只阻止新领取，已领取记录不回退；`locked`/`planned` 只登记不入表。
- 文件必须登记 `data/内容清单.json`；清单变更按官方种子迁移登记新旧 SHA-256 与 Git provenance，
  自定义/未知种子保留、冲突回退。

## 边界

不新增七日目标条目、不改奖励数值、不新增命令或数据库表；不引入新的来源事件或补做规则。
