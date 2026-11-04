# v0.7 道途转修内容基线

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.7`，
`rule_version=paths-0.7.0`。本版只把 `content-v0.1`、`workflow.md` 与 `use-cases.md` 已冻结、
运行时却从未接入的首阶段道途切换做成完整切片；`paths.rebuild`（元婴重构）仍不开放。

## 1. 公开取得：洗心转道令

`领取转修令`（别名 `请领转修令`、`转修令`）在角色入道且达到筑基一层后发放
`item.token.path_respec` ×1；每名角色同时最多持有一枚。领取后进入 7 天冷却，用掉令牌后可
再次领取；冷却未满返回 `PATH_SWITCH_COOLDOWN`。令牌绑定角色、不可交易、堆叠上限 1，
不触发通用 `使用` 效果，只作为转修确认时的消耗凭据。既有管理员令牌
`item.token.change_path` 保持原样，不改成公开物品。

## 2. 转修规则 `path.switch.standard`

| 字段 | 值 |
|:--|:--|
| 境界 | 筑基 L1 |
| 费用 | 灵石 500、`item.token.path_respec` 1 |
| 转修冷却 | 604800 秒（7 天，自上次确认成功起） |
| 预览期限 | 900 秒（15 分钟） |
| 目标 | 除当前首要道途外的任一 `active` 道途 |

`support` 必须同时指定采矿、烹饪、炼丹、炼器或布阵之一；其它道途不接受辅修参数。
目标与当前道途相同返回 `PATH_SWITCH_INVALID`，不生成预览。

## 3. 两阶段流程

`转修道途 <道途> [辅修]` 生成冻结计划：旧/新道途、目标辅修、费用、保留/冻结/清理项、
过期时间与操作 ID 一并写入 `path_switch_plans`。预览不扣令牌、不扣灵石、不改角色。
旧 `pending` 计划在同一事务内标记 `expired`，每名角色同时只有一个待确认计划。

`确认转修` 重新校验角色仍满足境界、路径未变、无领域/道果、无进行中的长动作，再在同一事务
扣除 500 灵石与 1 枚令牌，更新 `path_key` 与 `subprofession_key`，计划置 `confirmed`，写
`path.confirm_switch` operation。同 operation 重放返回首次结果；不同 operation 复用已确认
计划返回 `PATH_SWITCH_STATE`。`取消转修` 只把最新待确认计划置 `cancelled`，不扣资产。

预览过期后确认返回 `PATH_SWITCH_PREVIEW_EXPIRED`，计划置 `expired`，零扣。确认失败
（缺令、灵石不足、状态冲突、长动作）均不改变角色、资产或计划状态。

## 4. 保留、冻结与清理

- **保留**：公共境界、修为、灵石、行囊、灵兽/灵骑、已学神通、装备实例、旧道脉节点。
  旧道脉与旧神通在旧道途下继续生效，切回旧道途即可恢复，不需要重新购买。
- **冻结**：旧道途主动技能与旧道途专属装备效果在新道途下不进入战斗/属性快照；记录不删除。
- **清理**：离开辅修时清除 `subprofession_key`；已结算生产订单、产物与历史 operation 不受影响。
  进入辅修时必须选择一门辅修并写入同一字段。
- 旧道脉已用天赋点不返还、不折算；新道途道脉从第 1 阶起修习。

## 5. 未开放边界

已选择领域（`domain_key` 非空）或已得道果（`dao_fruit_key` 非空）的角色返回
`PATH_SWITCH_CONFLICT`，不能通过本版转修清洗终局状态。`paths.rebuild` 的元婴重构、道途等级
继承、一次性剧情任务、道脉重置、领域改选、跨服与支付均不在本版范围。

## 6. 验收

`test_path_switch_content.py` 校验合同字段、引用与拒绝变体；`test_path_switch.py` 覆盖领取与
冷却、预览/确认/取消、灵石与令牌扣除、同 operation 回放、不同 operation 复用计划、计划过期、
领域冲突、辅修进入/离开、旧道脉/神通/装备保留、重启后计划与角色状态、帮助命令与 QQ/OneBot
降级。回归 `test_path_content.py`、`test_talent.py`、`test_help.py`、`test_documentation.py`、
`test_content.py`、`test_m9_content_integrity.py`、种子迁移受影响组。
