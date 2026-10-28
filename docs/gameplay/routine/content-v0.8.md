# v0.8 道历与运营循环内容基线（功业录数据化）

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.8`，`rule_version=routine-0.8.0`。

| 系统 | 稳定键/准入 | 参数与结算 |
|:--|:--|:--|
| 功业录 | `data/功业/功业.json`（kind `achievement`） | 条目字段 `key`/`label`/`source_event`/`reward`/`status`，地方名望奖励另带 `local_reputation_key` |
| 既有五条 | `achievement.first_checkin`、`first_craft`、`first_dispatch`、`codex_5`、`tower_10` | 语义与数值不变：名望 3／服务信誉 2／道号 `title.dispatch_helper`／名望 5／道号 `title.first_tower_clear` |
| 新增一条 | `achievement.three_day_checkin`（三日不辍） | 来源 `routine.checkin.daily:3`（第三条问安），奖励 `local_reputation` 5，地点 `local.xuantian.new_town` |
| 展示与领取 | `功业录` / `领取功业 <序号>` | 序号按文件声明顺序解析；`active`/`open` 可领取，`closed` 保留占位但不再可领，`locked`/`planned` 不入表 |

## 合同

- 定义不再写在 Python：`routine/achievement_content.py` 解析并校验文件，
  `routine/rules.py` 由内容派生 `ACHIEVEMENTS`，`achievement()` 可按传入内容解析。
- `key` 必须以 `achievement.` 开头且唯一；`label`、`source_event` 非空。
- `reward` 允许键只有 `local_reputation`、`service_reputation`（正整数）与 `title_key`
  （已存在且未关闭的道号）。有地方名望奖励时必须声明可解析的 `local_reputation_key`，
  无该奖励时不得声明。
- 文件必须登记 `data/内容清单.json`；未登记或全部条目缺失时整域拒绝加载，绝不回退到
  旧硬编码表。
- `status` 只接受 `active`/`open`/`closed`/`locked`/`planned`：前两者可领取；`closed`
  保留在表中作为占位，未领取显示“内容未开放”、领取返回 `CONTENT_CLOSED`，已领取记录与
  原始奖励不变；`locked`/`planned` 只登记不展示。未知状态整域拒绝，不静默丢条目。
- 完成判定沿用既有来源投影（业务表或 `activity_events.event_key`），领取沿用 operation
  回放与 `achievement_claims` 唯一约束，奖励走共享资产事务，语义与旧实现一致。

## 边界

不新增命令、数据库表或奖励类型；不改既有五条功业的来源与数值；不把未开放的地图/塔层
写成可领取条件。
