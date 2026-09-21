# v0.4 属性内容基线：化神领域数值

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.4`，`rule_version=stats-0.4.0`。

## 1. 化神成长与领域资源

化神突破成功时增加气血 +1,000、灵力 +800、先手 +20；初始化 `domain_power=100`、`domain_charge=150/150`、`realm_resistance=1000 bp`。上述值由突破 operation 一次性写入。

| `stat_key` | 计算 | 上限/恢复 | 用途 |
|:--|:--|:--|:--|
| `domain_power` | `100 + equipment_bp/100 + path_bonus + event_bonus` | 硬上限 500 | 领域技能强度、领域对抗 |
| `domain_charge` | 每日恢复至 150 | 0–150，不累积 | 每场领域激活成本 |
| `realm_resistance_bp` | 1000 + 盟约 + 装备 + 领域 | 硬上限 7500 bp | 跨界/领域环境损失 |
| `domain_damage_bp` | `min(6000, domain_power*10)` | 单场 +6000 bp | 只用于领域标签技能 |

`domain_power` 不是普通增伤来源；领域伤害先按双方领域状态、地点和冲突规则结算，再应用 `domain_damage_bp`。同一来源不得同时提供 `domain_power` 与普通攻击乘区。

## 2. 领域对抗与裂痕

双方均激活领域时，计算 `power_delta = clamp(attacker_domain_power - defender_domain_power, -200, 200)`；攻击方领域效果调整 `power_delta*10 bp`，防守方反向调整。领域对抗不使任何一方效果低于 0，也不超过各技能定义的硬上限。

`domain_crack`：化神突破失败或领域崩解产生。默认 24 小时；期间 `domain_power` 保留但不可激活领域，`domain_charge` 仍可恢复到 150，普通修炼 -1500 bp。提前恢复成本见 progression v0.4；不可叠加缩短为负时间。

## 3. 快照、错误与验收

领域/战斗/生产创建 `DomainSnapshot`，保存领域键、力量、能量、抵抗、冲突对象、地点、道途与版本。错误：`DOMAIN_POWER_CAP`（警告）、`DOMAIN_CHARGE_INSUFFICIENT`、`DOMAIN_CRACK_ACTIVE`、`DOMAIN_CONFLICT`、`REALM_RESISTANCE_CAP`。

关闭 v0.4 后不再生成新领域快照，旧快照仍可结算。验收：领域日恢复不双加；力量差值夹断正确；裂痕不删除领域选择；领域伤害不进入普通增伤乘区；抵抗上限有来源解释。