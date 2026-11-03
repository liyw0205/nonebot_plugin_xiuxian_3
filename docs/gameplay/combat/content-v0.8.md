# v0.8 战斗内容基线：器修机关

`data/战斗/实体.json`（kind `entity`）此前只有一条 `device.scout_doll` 草稿并长期保持
`status: locked`，运行时没有任何加载器、消费者或命令，属于文档已冻结但未接线的合同缺口。
本版把这条记录补成可玩的器修机关，并保持与既有 `skill.device.scout_doll`（现名「机弩穿云」）
完全分离：技能是主动招式，机关是独立的随行实体，两者不共用键、不互相改写。

## 数据合同

| 字段 | 值 | 说明 |
|:--|:--|:--|
| `key` | `device.scout_doll` | 必须以 `device.` 开头 |
| `entity_type` | `summoned_device` | 当前唯一支持的实体类型 |
| `owner_path_key` | `device` | 必须引用已登记道途 |
| `status` | `active` | `locked`/`open` 记录可加载但不开放组装 |
| `required_realm` / `min_layer` | `qi_sensing` / `1` | 准入同时校验道途与境界层 |
| `max_instances` | `1` | 一名修士至多一件 |
| `assembly` | 灵石 120、木材 2、铁石 1 | 组装成本 |
| `maintenance` | 灵石 20、木材 1 | 每次维修步的成本 |
| `durability` | `max_bp: 10000`、`loss_per_action_bp: 400`、`repair_bp_per_material: 2500` | 耐久、损耗与维修步长 |
| `combat` | `attack_multiplier_bp: 5000`、`duration_rounds: 3`、`max_actions_per_battle: 3` | 攻击为自身的 50%，参与三回合，每场至多三次 |
| `codex_entry_key` | `codex.path.device` | 复用器修图鉴，不新增条目 |

## 数值理由

- 50% 攻击倍率沿用 `docs/gameplay/combat/content-v0.1.md` 与
  `docs/foundation/paths/content-v0.1.md` 的冻结描述，机关是补足攻守间隙的辅助伤害，
  不能替代本命法器；三回合与每场三次是同一约束的两种表述，短战斗不能囤次数、长战斗不能超发。
- 折旧 400 bp/次意味着满耐久可支撑 25 次出手（约八场满额战斗），与「一件机关、不能随意拆解」
  的定位一致；维修按缺口向上取整，满修固定四步，材料与灵石都来自近郊可得资源。
- 组装与维修的判定全部在事务内完成：材料、灵石、道途、境界、数量上限、状态（部署/损坏）
  任一不满足即整笔回滚，不产生半成品实例。

## 运行时与持久化

- `device/entity_content.py` 负责解析与校验：键前缀、字段集合、实体类型、状态、道途/境界/物品/图鉴
  引用、成本块形状、耐久上限与损耗边界、回合 1–20（与战斗引擎 `MAX_TURNS` 对齐）、
  动作上限不超持续回合、别名唯一。任何违规抛 `ContentError`，并在导入期构建，部署校验同样失败。
- `device/entity_rules.py` 全是纯函数：准入缺项、耐久计算、维修步数、动作许可
  （`plan_actions(duration_rounds, max_actions_per_battle, used_actions, round_no)`）、
  战斗快照冻结（`device_frozen_snapshot`）。
- 新表 `device_instances` 保存实例、耐久、`active|broken` 状态与部署标记，
  并以 `(player_id) WHERE deployed = 1` 的唯一索引保证同一玩家最多一件机关处于部署态。
- `DeviceRepositoryMixin` 的五个入口都在单事务内完成并写 `operations`：同一 operation 重放返回原结果，
  输入不一致抛 `OperationConflictError`；进程重启后状态从表内恢复，不依赖内存。

## 战斗接入

起手时把已部署机关冻结进 `snapshot.player.device`（实例号、倍率、回合、动作上限、每次损耗）。
自动回合在玩家行动之后追加一条玩家侧行动：`strategy_key = strategy.device.scout_doll`、
`skill_key = device.scout_doll`，伤害为玩家攻击 × 50%，命中与暴击沿用公共 roll，
随机种子加 `:device` 后缀以保持回放稳定。`state.device_actions` 随回合写入快照，
因此重放与续算都得到同一结果。

`resolve_battle` 是耐久唯一写入点：按 `device_actions × loss_per_action_bp` 扣减，归零置 `broken`
并自动收回部署。结算本身带 operation 幂等，重复调用不会二次扣耐久。

## 命令与呈现

`机关 [机关名]`、`组装机关`、`部署机关`、`收回机关`、`维修机关`（可省略机关名，默认唯一机关）。
稳定错误码：`DEVICE_NOT_FOUND`、`DEVICE_LIMIT_REACHED`、`DEVICE_REQUIREMENT`、
`DEVICE_MATERIAL_MISSING`、`DEVICE_BROKEN`、`DEVICE_STATE`、`INVALID_DEVICE_COMMAND`、
`LEDGER_CONFLICT`，全部零写。

QQ 原生 Markdown 下，状态页按当前状态只挂一个动作按钮（待命→部署、已部署→收回、损坏→维修），
未组装时只给 `组装机关` 蓝字预填；OneBot 与纯文本降级为可读命令与「可发送：…」，不暴露稳定键。
`修仙帮助 生活` 追加由内容派生的机关段落，不含按钮网格。

## 非目标

不改动 `skill.device.scout_doll`；不实现 `domain.machine_city`（机关数量 +3）与
`fruit.machine_heaven`（永久耐久化），它们仍按域效果与道果的既有锁定语义运行；
不做机关交易、拆解或跨服转移。
