# v0.9 功业内容基线：计数型功业与道统十役

功业支持单次事件达成与按操作次数累计两种口径。未设置 `required_count` 时要求一条匹配的
`source_event`；累计目标还须以 `count_event_key` 限定实际操作类型，避免把不同任务混计。

## 新增口径

功业记录新增两个可选字段：

| 字段 | 含义 |
|:--|:--|
| `required_count` | 需要的事件次数，正整数，缺省 1（即旧口径） |
| `count_event_key` | 计数时必须匹配的 `payload.dispatch_key`；当 `required_count > 1` 时必填 |

校验规则（`routine/achievement_content.py`）：

- `required_count` 必须是正整数，布尔值不算；
- `required_count > 1` 而未给 `count_event_key` 视为内容错误——否则会把同名事件全部计入；
- `required_count == 1` 却给了 `count_event_key` 也视为错误，避免语义歧义。

## 运行时

`routine/repository.py` 的领取路径按 `required_count` 分流：等于 1 时沿用旧的单事件判定，
大于 1 时用 `_honor_counted_operation` 统计 `activity_events` 中该玩家、该 `event_key`
且 `payload.dispatch_key == count_event_key` 的行数；若 payload 带 `outcome` 则只认
`success`——失败的派单不算服务。达到次数后返回**最近一次**事件的 `source_operation_id`
作为称号来源，保证 `activity_events`/称号授予的 provenance 指向真实操作。

## 道统服务功业

| 键 | 值 |
|:--|:--|
| `achievement.dao_service` | `道统十役`；`source_event: specials.dispatch.settled`；`count_event_key: dispatch.dao_service`；`required_count: 10`；奖励 `title_key: title.dao_service` |
| `title.dao_service` | `道统执事`；来源事件 `routine.claim_achievement` |

十次道统派单**成功**结算后可领取，得称号「道统执事」。失败派单与其他派单键都不计入。

## 非目标

不改任何既有六条功业的判定、不改派单本身的结算与产出、不新增表、不改称号装备规则。
