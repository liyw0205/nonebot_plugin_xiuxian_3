# v0.6 道历与运营循环内容基线

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.6`，`rule_version=routine-0.6.0`。终局运营为道统服务和新篇章准备，不干预飞升/留界结算。

| 系统 | 稳定键/准入 | 参数与结算 |
|:--|:--|:--|
| 灵木 | `ritual.spirit_tree.dao`：道统/留界据点公共项目 | 49 日周期；收获建设券 2、灵石 900–1200、道统名望 +10；终局角色不能转移树权 |
| 机缘寻宝 | `gacha.fate.dao_echo`：合道 L1 或公开道统服务资格 | 单抽 800、十连 7200；只出新篇章线索、展示、服务权限；禁止道果/飞升凭证 |
| 行卷 | `pass.wayfaring.dao` | 60 级；终局赛季奖励只发道号/世界志/服务资格 |
| 功业/道号 | `achievement.dao_service` | 10 次道统服务得 `title.dao_service`；可公开或私密展示 |
| 道契 | `dao_contract.dao_monthly` | 仅提供维护/精力/名望；飞升后权益冻结为只读 |
| 七日目标 | `quest.seven_day.new_chapter` | 终局后新篇章预览；不得改变 `ending_state` |
| 密令 | `code.dao_recovery` | 只发公共维护物资；所有终局密令按角色/赛季唯一 |

终局资产表、道果、天劫债、飞升功勋、飞升凭证不得被本域读取后写回普通资产；违规请求返回 `ENDGAME_ASSET_FORBIDDEN`。