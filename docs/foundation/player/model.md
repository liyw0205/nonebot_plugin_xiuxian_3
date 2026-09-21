# 角色域：数据模型

## Player

| 字段 | 约束 |
|:--|:--|
| `player_id` | 稳定唯一字符串 |
| `platform` | 平台枚举 |
| `platform_user_id` | 原样保存，不做数值化 |
| `status` | `active`、`suspended`、`deleted` |
| `stage` | `new_user`、`mortal`、`seeker`、`cultivator` |
| `name` | 1-24 字符，按规则唯一 |
| `qualification_snapshot_id` | 寻仙后生成，不覆盖 |
| `path_key` | 首要道途，可空 |
| `location_key` | 当前地点 |
| `created_at`/`updated_at` | UTC 时间 |
| `rule_version` | 当前规则版本 |

## QualificationSnapshot

保存 `snapshot_id`、属性值、灵根倾向、随机池版本、随机结果摘要、生成 operation ID 和创建时间。快照不可变。

## NameHistory

保存旧名称、新名称、原因、操作者、operation ID 和时间。改名失败不写历史。