# v0.1 道途内容基线

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.1`，`rule_version=paths-0.1.0`。道途选择由 `player.enter_cultivation` 结算；被动/主动键保存到构筑快照，不由命令层按展示名判断。

首版六条道途各开放 1 个被动、1 个主动和 1 个状态机制。

| `path_key` | 被动键与效果 | 主动键与效果 | 状态/代价 |
|:--|:--|:--|:--|
| `body` | `trait.body_temper`：体魄转气血效率 +15% | `skill.body.heavy_strike`：体魄 1.4 倍伤害，消耗 10 战意 | 战意，满 100 才能保命 |
| `spell` | `trait.spell.spirit_focus`：法术基础值 +10% | `skill.spell.water_bolt`：灵力 1.5 倍伤害，消耗 18 灵力 | 施法冷却 1 回合 |
| `device` | `trait.device.maintenance`：法器耐久损耗 -20% | `skill.device.scout_doll`：召唤 1 个机关，持续 3 回合 | 操控上限 1 |
| `demonic` | `trait.demonic.blood_contract`：低血量时伤害 +20% | `skill.demonic.pain_exchange`：消耗 8% 当前气血，伤害 +45% | 侵蚀 +12/次 |
| `beast` | `trait.beast.wild_sense`：探索发现率 +10% | `skill.beast.partial_transform`：3 回合身法 +20% | 化形稳定度 -5 |
| `support` | `trait.support.craft_memory`：生产熟练度收益 +15% | `skill.support.quick_assessment`：生产预览质量 +10 | 每日精力消耗 +2 |

道途选择在 `seeker -> cultivator` 时完成。首版不开放免费切换；首次切换需要筑基、`item.token.change_path` 和 500 灵石。