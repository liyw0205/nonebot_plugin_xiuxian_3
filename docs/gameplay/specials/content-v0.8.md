# v0.8 闲居中阶路线与准入扩展

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.8`，
`rule_version=specials-0.8.0`。本版把 `content-v0.2.md`–`content-v0.6.md` 记录在案、但运行时一直
只有题录的中阶闲居路线接入：闲居准入新增境界层与贸易许可两类门槛，并新增四条中阶路线。

## 1. 数据合同

`data/生活/生活.json`（kind `livelihood`）新增四条 `record_type: idle_route` 记录，
`data/奖励/奖励.json` 新增八条对应奖池（每条路线一个完整奖池与一个单结局保底池）：

| 路线 | `key` | 门槛 | 安排 | 完整所得 | 逾时所得 | 每日 |
|:--|:--|:--|:--|:--|:--|--:|
| 矿区看守 | `idle.cloud_mine_watch` | 筑基 L4 | 6 小时；精力 2 | 云铁 1–3、灵石 30–50 | 云铁 1 | 1 |
| 云城店铺 | `idle.cloud_city_shop` | 云城名望 200 | 8 小时 | 灵石 60–100、云城名望 +2 | 灵石 40 | 1 |
| 魔界驿所 | `idle.demon_trade_post` | 有效 `permit.demon_trade` | 8 小时；体力 2 | 灵石 80–130、魔渊集市名望 +3 | 灵石 40 | 1 |
| 妖界栖地 | `idle.beast_habitat_watch` | 有效 `permit.beast_trade` | 8 小时；体力 2 | 粗糙灵米 1–2、灵叶 1–2、三界贸易口名望 +3 | 灵叶 1 | 1 |

奖池键为 `reward_pool.idle.<路线>` 与 `reward_pool.idle.<路线>.fallback`；保底池只有一条结局，
完整池按权重抽取。路线全部为 `status: active`，不改动 v0.1 的四条基础路线及其奖池。

## 2. 准入模型扩展

`IdleRouteDefinition` 新增三个字段，由 `specials/idle_rules.py` 解析与校验：

- `requirements.realm`：必须是 `{key, min_layer}`，key 为已开放境界，层数 1–10；
  缺字段、未知境界、非正数或超过十层一律抛 `ContentError`。
- `requirements.required_permit`：必须是能解析到已开放 `trade_permit` 的稳定键，
  未知或许可关闭时抛 `ContentError`，避免把玩家挡在无法取得的凭证后面。
- 两者都可省略；省略表示无该门槛，v0.1 路线行为不变。

`挂机预览` 逐条给出缺失项：境界不足显示「境界不足」，缺许可显示「需要有效的贸易许可」，
并保留既有地点、地方名望、居所、工具与次数提示。`开始挂机` 在任一门槛未满足时以
`IDLE_REQUIREMENT_MISSING` 零写拒绝。

## 3. 与早期题录的差异（有意收窄）

- 矿区看守的题录写作「筑基 L4 或矿区名望 150」。云铁矿区没有
  `local_reputation_maximum`，无法承载地方名望门槛，运行时改以筑基 L4 单一门槛实现；
  不新增名望维度，也不放宽世界准入。
- 魔界驿所与妖界栖地的「图鉴线索」不再发放：现有 `codex.place.*` 条目是抵达型发现，
  由挂机产出会让图鉴来源失真；本版只发材料、灵石与地方名望，图鉴来源保持既有玩法。
- 云城店铺沿用真实产出的 `local.xuantian.cloud_city`（云城派遣成功 +4/+5、部分 +2）；
  门槛 200 需要持续积累，不提供捷径。

## 4. 结算、恢复与呈现

计时、冻结奖励、每日次数、60 秒撤回窗口、24 小时完整领取与 48 小时上限、事务与
operation 回放全部沿用 `idle.md` 的既有语义，本版只新增数据与准入字段。领取所得中的
地方名望仍按地点上限封顶，物品、灵石、名望、会话状态与 operation 同事务提交；
重启后运行中的安排继续按冻结快照结算。

`挂机预览` 的 `requirements` 载荷新增 `required_realm`、`required_layer`、
`required_permit`，无门槛时为 `null`/`0`，玩家文案只显示可读缺失项，不暴露稳定键。
不新增命令、按钮或帮助段；`修仙帮助 生活` 的挂机段沿用既有一句。

## 5. 验收

`test/test_idle_mid_routes.py` 覆盖：

- 四条路线的 `required_realm`/`required_layer`/`required_permit`/地方名望与完整、保底奖池；
- 筑基 L3 预览矿区看守显示「境界不足」，L4 后可开始；
- 云城名望 199 显示「地方名望不足（需要 200）」，200 后可开始；
- 无 `permit.demon_trade`/`permit.beast_trade` 显示「需要有效的贸易许可」，签发后可开始；
- 既有 `idle.town_errand` 在同一角色上不受新门槛影响。

回归：`test_idle.py`、`test_dispatch.py`（共用地方名望与许可读取）、`test_documentation.py`。
