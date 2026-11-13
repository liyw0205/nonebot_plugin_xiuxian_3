# v0.8 元婴道途重构内容基线

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.8`，
`rule_version=paths-0.8.0`。本版把 `content-v0.3.md` 已冻结数值、运行时长期缺失的
`paths.rebuild` 做成完整切片：三界主线已经发放 `item.token.rebuild_path` 与
`story.mainline.three_realms` 旗标，本版补上定义、预览、确认、一次性记录与道脉继承。

## 1. 公开取得

三界主线（调停、契约、共生任一线）第五关结算时发放 `item.token.rebuild_path` ×1 并写入
`story.mainline.three_realms`；该旗标同时是三界声望各 1000 的完成证据。令牌绑定角色、
不可交易、堆叠上限 1，不进入通用掉落池，也不触发 `使用` 效果，只在重构确认时消耗。

`data/道具/重构令.json` 是首个把该令牌登记为正式 `item` 的定义；既有主线奖励键保持不变，
不需要迁移旧存档。

## 2. 重构规则 `path.rebuild.standard`

| 字段 | 值 |
|:--|:--|
| 境界 | 元婴 L1 |
| 前置旗标 | `story.mainline.three_realms` |
| 三界声望 | `xuantian`、`demon`、`beast` 各 ≥ 1000 |
| 费用 | 灵石 50000、`item.token.rebuild_path` 1 |
| 预览期限 | 86400 秒（24 小时） |
| 等级继承 | `max(1, old_level - 2)` |
| 次数 | 每名角色一次，永久记录 |

`old_level` 取旧道途树中已学节点的最高 `tier`；没有已学节点时为 0，继承下限仍为 1。
目标道途必须是 `active` 且不同于当前 `path_key`。目标为 `support` 时必须同时给出采矿、
烹饪、炼丹、炼器或布阵之一，其它道途不接受辅修参数。

## 3. 两阶段流程

`道途重构预览 <道途> [辅修]`（别名 `重构道途`）校验境界、旗标、三界声望、一次性次数、
终局状态、长动作、令牌与灵石，然后计算旧树等级与目标树继承节点，写入
`path_rebuild_plans`。预览在同一事务内把该角色旧的 `pending` 计划置 `expired`，每名角色
同时只有一个待确认计划。预览零扣、不改 `path_key`、不写 `path_rebuilds`。

`确认道途重构`（可选计划 ID）重新校验同一组前置与旧树等级，再在同一事务：

1. 扣除 50000 灵石与 1 枚重构令；
2. 更新 `players.path_key` 与 `subprofession_key`；
3. 写 `path_rebuilds`（旧/新道途、旧等级、继承等级、旧树节点快照）；
4. 为目标树插入 `tier <= inherited_level` 的 `learned` 节点，`cost_points=0`，不消耗天赋点；
5. 把计划置 `confirmed` 并写 `path.confirm_rebuild` operation。

同 operation 重放返回首次结果；不同 operation 复用已确认计划返回 `PATH_REBUILD_STATE`。
`取消道途重构` 只取消最新待确认计划，零扣。预览过期后确认返回
`PATH_REBUILD_PREVIEW_EXPIRED`，计划置 `expired`，零扣。确认时任一前置失败均不改变角色、
资产或计划状态。

## 4. 保留、冻结与继承

- **保留**：公共境界与修为、行囊、灵石、灵兽/灵骑、已学神通、装备实例、旧道脉节点与旧
  道脉已花天赋点。旧节点不删除也不返还，旧道途冻结留档，切回旧道途后继续可用。
- **冻结**：旧道途主动技能与旧道途专属装备效果在新道途下不进入战斗/属性快照；记录保留。
- **继承**：目标树按 `max(1, old_level - 2)` 免费写入 `learned` 节点。目标树已有同键节点时
  保留原节点，不重复写入，也不删除目标树更高级的历史节点。
- **清理**：离开 `support` 时清除 `subprofession_key`；已结算订单、产物与历史 operation 不受
  影响。进入 `support` 时把目标辅修写入同一字段。
- 已选择领域（`domain_key` 非空）或已得道果（`dao_fruit_key` 非空）返回
  `PATH_STATE_CONFLICT`，不能借重构清洗终局状态；进行中的长动作同样拒绝。

## 5. 兼容与回退

`path_rebuilds.player_id` 唯一，保证每角色一次；一次性记录不因转修、重置或重启消失。
旧存档没有 `path_rebuild_plans` / `path_rebuilds` 表时由 schema 初始化补齐，不需要数据迁移。
旧 `path_key`、旧节点和历史装备不改写；新表只追加。重构不改变公共境界、修为、灵石上限、
灵兽、灵骑、污染、血脉或契约状态。`paths.rebuild` 之外的领域改选、跨服与支付仍不开放。

## 6. 帮助与文案

`帮助 修炼` 在道途转修、道脉重置之后追加「道途重构（元婴）」段，列出预览、确认、取消三条
命令；无参数 `道途重构预览` 列出当前道途与可重构道途，辅修写法在提示中给出。所有回复使用
现有 `command_link` 蓝字预填，不附按钮网格；纯文本适配器由共享渲染器降级。

## 7. 验收

`test/test_path_rebuild.py` 覆盖：

- 内容合同字段、费用、三界声望、等级扣减和未知/非法变体；
- 元婴、旗标、三界声望、令牌、灵石五类失败均零副作用；
- 预览冻结旧树 3 阶、继承 1 阶，确认扣 50000 灵石与 1 令，旧树 3 节点保留，目标树 1 节点；
- 同 operation 回放、每角色一次、二次预览 `PATH_REBUILD_LIMIT_REACHED`；
- 24 小时过期零扣、旧树等级变化冲突、取消后确认 `PATH_REBUILD_NOT_FOUND`；
- `support` 缺辅修拒绝、指定辅修成功；
- 重启后次数仍生效、`帮助 修炼` 输出三条命令。

种子侧在 `scripts/seed_migrations.json` 登记 `道具/重构令.json`、`道途/重构.json` 与更新后的
`内容清单.json`；官方种子迁移须在更新后校验发布字节一致，并保留未知或自定义文件。
