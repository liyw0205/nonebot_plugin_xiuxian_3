# v0.7 灵兽内容基线：相伴与御兽体质

灵兽此前只有经验与等级会变（`喂养灵兽` 加经验），`affinity` 字段虽然存在于
`companion_instances` 并由 `蜕变` 以 `required_affinity` 读取，却**没有任何增长路径**，
`constitution.beast_affinity`（御兽，`+5` 亲和）也长期是 `locked`、效果无人消费。

本版补上这两处缺口，形成一条完整可玩链：与灵兽相伴 → 亲和增长 → 满足蜕变的亲和要求。

## 数据合同

`data/灵兽/互动.json`（kind `companion_interaction`）：

| 字段 | 值 | 说明 |
|:--|:--|:--|
| `key` | `interaction.companion.company` | 必须以 `interaction.` 前缀 |
| `base_affinity` | 3 | 每次基础亲和 |
| `constitution_effect` | `beast_affinity` | 与之联动的体质效果类型 |
| `affinity_per_constitution_point` | 1 | 每点体质效果值追加的亲和 |
| `affinity_cap` | 100 | 亲和上限 |
| `stamina_cost` | 10 | 每次消耗体力 |
| `daily_limit` | 1 | 每日一次（按 UTC 日） |
| `aliases` | 相伴灵兽 / 陪伴灵兽 | 命令别名 |

校验：键前缀、字段集、名称/描述非空、状态枚举、`base_affinity` 与 `affinity_cap` 为正、
`base_affinity <= affinity_cap`、给了 `affinity_per_constitution_point` 就必须点名
`constitution_effect`、别名全局唯一。

## 亲和计算

`affinity_gain = base_affinity + (体质效果值 × affinity_per_constitution_point)`，
仅在体质效果 `type` 等于 `constitution_effect` 时计入；其他体质（如 `max_hp_bp`）不产生加成。
御兽 `+5` 时单次亲和为 8，无御兽时为 3。结果按 `affinity_cap` 封顶，实际写入的是
`min(cap, current + gain) - current`。

## 运行时

命令 `灵兽相伴 <灵兽编号或键>`（别名 `相伴灵兽`、`陪伴灵兽`）：

- 每日一次，按 `operations` 表中同名操作当天的记录数判定；同日再试返回
  `COMPANION_COMPANY_SPENT`，且不改变任何状态。
- 体力不足返回 `COMPANION_COMPANY_INSUFFICIENT`；休养/受伤中的灵兽返回 `COMPANION_RESTING`；
  已归隐返回 `COMPANION_NOT_FOUND`。
- 成功时在同一事务内扣体力、写亲和、记 `operations`；`operation_id` 重放返回冻结结果，幂等。

## 御兽体质

`constitution.beast_affinity` 由 `locked` 改为 `active`，并加入
`advancement/constitution_rules.CONSUMED_EFFECT_TYPES`；`stats/rules._constitution_bonus`
把 `beast_affinity` 视为**无战斗加成**（返回空），避免既有属性计算因未知类型报错。

## 非目标

不改喂食、休养、蜕变本身的数值与判定；不新增表（每日上限沿用 `operations`）；
不引入新的亲和消耗；不改灵兽种类与灵具。
