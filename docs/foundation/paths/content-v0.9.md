# v0.9 独立辅修切换内容基线

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.9`，
`rule_version=paths-0.9.0`。本版补上 `docs/foundation/paths/use-cases.md` 与 `model.md` 长期标注
“独立 `select_subprofession` 尚未接入”的缺口：辅修玩家不必换整个道途，也能改修辅修。

## 1. 内容数据

新增 `data/道途/辅修切换.json`，kind=`subprofession_switch`：

| 字段 | 值 |
|:--|:--|
| key | `subprofession.switch.standard` |
| 名称/别名 | 辅修切换 / 切换辅修、改修辅修 |
| 道途 | 仅 `support` |
| 境界 | 筑基 L1 |
| 费用 | 灵石 2000 |
| 冷却 | 604800 秒（7 天，自上次确认成功起） |
| 预览期限 | 900 秒（15 分钟） |

目标只能是 `support` 路径下 `active` 的采矿、烹饪、炼丹、炼器、布阵之一，且必须不同于
当前 `subprofession_key`。本版不新增物品、地点、敌人或辅修种类。

## 2. 运行流程

`辅修预览 <辅修>` 校验角色 `path_key='support'`、筑基 L1、已有当前辅修、目标存在且不同、
无进行中的长动作、冷却已过、灵石足够，然后生成 15 分钟冻结计划，写入
`subprofession_switch_plans`。预览零扣、不改 `subprofession_key`；同一事务把该角色旧的
`pending` 计划置 `expired`，每角色同时只有一个待确认计划。

`确认辅修 [计划ID]` 重新校验同一组前置，再在同一事务：

1. 扣除 2000 灵石；
2. 更新 `players.subprofession_key`；
3. 写 `subprofession_switches` 历史（旧/新辅修、operation、时间）；
4. 计划置 `confirmed` 并写 `subprofession.confirm_switch` operation。

同 operation 重放返回首次结果；不同 operation 复用已确认计划返回
`SUBPROFESSION_SWITCH_STATE`。`取消辅修` 只取消最新待确认计划，零扣。预览过期后确认返回
`SUBPROFESSION_SWITCH_PREVIEW_EXPIRED`，计划置 `expired`，零扣。确认时任一前置失败均不改变
角色、灵石或计划状态。

错误码：`SUBPROFESSION_SWITCH_NOT_SUPPORT`、`SUBPROFESSION_SWITCH_INVALID`、
`SUBPROFESSION_SWITCH_FUNDS`、`SUBPROFESSION_SWITCH_COOLDOWN`、
`SUBPROFESSION_SWITCH_NOT_FOUND`、`SUBPROFESSION_SWITCH_PREVIEW_EXPIRED`、
`SUBPROFESSION_SWITCH_STATE`、`SUBPROFESSION_SWITCH_CONFLICT`。

## 3. 保留与兼容

- 只改 `subprofession_key`；公共境界、修为、灵石上限、行囊、道脉、道途、灵兽、灵骑、
  污染、血脉、契约与领域不变。
- 旧生产订单的辅修已写在订单快照里，继续按快照结算；新订单读更新后的键。
- 生产熟练度按辅修键保存历史，切回旧辅修时原熟练度仍在。
- 冷却由 `subprofession_switches.created_at` 推导，不新增 `players` 列。
- 旧存档没有两张新表时由 schema 初始化补齐，不需要数据迁移。
- 非 `support` 道途返回 `SUBPROFESSION_SWITCH_NOT_SUPPORT`；改道途仍走
  `path.switch.standard`，元婴重构仍走 `paths.rebuild`。

## 4. 帮助

`帮助 修炼` 在道途转修、道脉重置、道途重构之后追加「辅修切换（辅修道途）」段，列出：

- `辅修预览 炼丹`
- `确认辅修`
- `取消辅修`

使用既有 `command_link` 蓝字预填；不新增按钮网格。

## 5. 验收

`test/test_subprofession_switch.py` 覆盖：

- 内容合同字段、仅 support、单币种、冷却与非法变体拒绝；
- 非辅修道途、同目标、未知目标、缺当前辅修、灵石不足分别零副作用拒绝；
- 预览不改角色，确认扣 2000、更新 `subprofession_key` 并写历史与 operation；
- 7 天冷却内再次预览返回 COOLDOWN，冷却过后可再次切换；
- 预览过期零扣、取消后确认返回 STATE、确认后不同 operation 返回 STATE；
- 同 operation 回放不重复扣费；
- 重启后历史仍在、`帮助 修炼` 输出三条命令。

种子侧在 `scripts/seed_migrations.json` 登记 `道途/辅修切换.json` 与更新后的
`内容清单.json`；官方种子迁移须在更新后校验发布字节一致，并保留未知或自定义文件。
