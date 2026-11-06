# v0.9 闲居终局路线与参与门槛

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.9`，
`rule_version=specials-0.9.0`。本版把 `content-v0.4.md`–`content-v0.6.md` 记录在案的三条终局闲居
路线接入运行时，并给闲居准入补上「公共项目参与度」与「宗门道统已定」两类门槛。

## 1. 数据合同

`data/生活/生活.json` 新增三条 `record_type: idle_route` 记录，`data/奖励/奖励.json` 新增六条奖池
（完整 + 单结局保底）：

| 路线 | `key` | 门槛 | 安排 | 完整所得 | 逾时所得 | 每日 |
|:--|:--|:--|:--|:--|:--|--:|
| 领域避难所看守 | `idle.domain_refuge_watch` | `project.domain_refuge` 贡献 ≥10 点 | 10 小时；体力 3 | 灵石 100–160、建设券 1、领域前线名望 +3 | 灵石 50 | 1 |
| 虚空补给看守 | `idle.void_supply_watch` | 炼虚 L1 | 12 小时；体力 4 | 灵石 140–220、建设券 1 | 灵石 70 | 1 |
| 道统据点看守 | `idle.dao_settlement_watch` | 宗门已有 `dao_route_state` | 12 小时；体力 4 | 灵石 180–280、建设券 2、道统服务名望 +3 | 灵石 90 | 1 |

奖池键为 `reward_pool.idle.<路线>` 与 `.fallback`；保底池只有一条结局。三条路线均为 `status: active`，
不改动既有八条路线及其奖池。

## 2. 新准入字段与校验

`specials/idle_rules.py` 新增两类 `requirements` 字段：

- `project_contribution = {project_key, min_points}`：`project_key` 必须解析到已开放的
  `record_type: public_project` 记录，`min_points` 为正整数；未知或关闭项目一律抛 `ContentError`。
- `dao_route: true`：布尔值；仅要求玩家所属活跃宗门存在 `dao_route_state`，不绑定具体路线。

`挂机预览` 逐条给出缺失项：参与度不足显示「参与度不足（需要 N 点）」，未定道统显示
「需要宗门已定道统」；`开始挂机` 以 `IDLE_REQUIREMENT_MISSING` 零写拒绝。参与度按
`livelihood_project_contributions` 中该玩家对同一 `project_key` 的历史贡献点数求和，不因周次重置。

## 3. 与早期题录的差异（按可达性收窄）

- 虚空补给看守的题录写作「完成 `void_supply.*` 合同 1 次」或 `local.void_supply` 名望。运行时
  没有 `void_supply` 地点、合同或可解析的本地名望上限（`void.portal`/`void.first_route`/
  `void.archive_ruins` 都没有 `local_reputation_maximum`），因此本版按虚空阶段入口收窄为
  炼虚 L1，不新增无法取得的名望维度。
- 道统据点看守的题录写作「参与 `project.dao_settlement`」。该公共项目在数据中不存在，
  本版改按真实可达的宗门道统状态判定（道统结算后写入 `dao_route_state`）。
- 领域避难所看守沿用真实项目 `project.domain_refuge` 的贡献点数（资源或服务贡献均计入），
  不新增项目、不发放项目奖励。

## 4. 结算与呈现

计时、冻结奖励、每日次数、60 秒撤回、24 小时完整领取、48 小时上限、事务与 operation 回放
沿用 `idle.md` 语义；本版只新增数据与准入字段。`挂机预览` 的 `requirements` 载荷新增
`required_project_contribution`（`[project_key, min_points]` 或 `null`）与 `required_dao_route`，
玩家文案只显示可读缺失项。不新增命令、按钮或帮助段。

## 5. 验收

`test/test_idle_endgame_routes.py` 覆盖：

- 三条路线的门槛字段、时长、体力与完整/保底奖池；
- 领域避难所看守在 0 贡献时显示「参与度不足（需要 10 点）」，补足 10 点后预览可开始；
- 虚空补给看守在筑基时显示「境界不足」，炼虚 L1 后可开始；
- 道统据点看守无宗门道统时显示「需要宗门已定道统」，写入道统后预览可开始；
- 既有 v0.1/v0.8 路线不受新门槛影响。

回归：`test_idle.py`、`test_idle_content.py`、`test_idle_mid_routes.py`、`test_documentation.py`。
