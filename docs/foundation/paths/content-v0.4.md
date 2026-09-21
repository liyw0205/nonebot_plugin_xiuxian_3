# v0.4 道途内容基线：化神领域

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.4`，`rule_version=paths-0.4.0`。领域是化神专属的战斗/生产状态，不是永久全局倍率。

## 1. 选择规则：`paths.choose_domain`

前置：`realm_key=soul_transformation`、首要道途等级 5、未选择领域、`item.domain_core` 1、灵石 10,000。选择创建 5 分钟确认会话；确认后消耗材料/灵石、写入 `domain_key`，同一 operation 回放原结果。取消、超时或前置失败不扣资产。每名角色只能一个领域；v0.4 不开放普通重选。

| 道途 | `domain_key` | 激活效果 | 每场成本与限制 |
|:--|:--|:--|:--|
| `body` | `domain.mountain_body` | 自身与相邻队友范围伤害 -2500 bp | 领域能量 30；单场最多 3 回合 |
| `spell` | `domain.elemental_sea` | 元素伤害 +2500 bp，元素控制命中 +800 bp | 能量 35；同一目标控制最多延长 1 回合 |
| `device` | `domain.machine_city` | 机关数量 +3，机关行动速度 +1000 bp | 能量 30、维护耐久 +20% |
| `demonic` | `domain.abyss_shadow` | 魔界伤害 +3500 bp，吸血上限 +1000 bp | 能量 30、污染 +15；污染达到 100 强制结束 |
| `beast` | `domain.ancestral_wild` | 妖界派生属性 +2500 bp，探索发现 +1500 bp | 能量 30、化形稳定 -10 |
| `support` | `domain.artisan_realm` | 生产时间 -2500 bp，品质分 +1000 bp | 能量 25、订单精力 +10 |

领域激活条件：当前 `domain_charge >= cost`、未处于 `domain_crack`、地点/战斗允许领域、同队无互斥领域。领域创建时固定双方属性、环境、队伍、成本和内容版本；激活失败不扣能量。

## 2. 领域冲突与状态机

```text
unselected -> selected -> inactive -> active -> inactive
active -> forced_end (energy=0 / state_conflict / pollution_cap)
selected -> frozen (domain_crack) -> inactive
```

同队最多一个攻击型领域（法/魔）和一个防御/建设型领域（体/器/妖/辅）；冲突时后发起者返回 `DOMAIN_CONFLICT`。领域不跨战斗/订单保存；生产领域仅对创建时绑定的订单有效。领域能量每日恢复到 150，不累积。

## 3. 错误、观测、关闭与验收

- 错误：`DOMAIN_NOT_ELIGIBLE`、`DOMAIN_ALREADY_SELECTED`、`DOMAIN_ENERGY_INSUFFICIENT`、`DOMAIN_CONFLICT`、`DOMAIN_CRACK_ACTIVE`、`LOCATION_DOMAIN_FORBIDDEN`。
- 观测：领域键、能量前后值、污染/稳定度/耐久变化、队伍冲突、持续回合/订单时间、来源快照。
- 关闭：停止新选择/激活；已激活战斗和订单按原版本结算，之后转为 `inactive`。
- 回滚：恢复前冻结领域入口；已选择领域保留，不能因回滚退还已消费的历史 `item.domain_core` 后再重选。
- 验收：资源不足不创建领域；冲突不扣第二个领域能量；魔修污染上限强制结束；生产领域不影响非绑定订单；相同 operation 不重复扣能量。