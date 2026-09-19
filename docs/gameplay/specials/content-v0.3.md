# v0.3 特色玩法内容基线：三界发现与异界派遣

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.3`，`rule_version=specials-0.3.0`。三界特色玩法使用许可、地区名望和快照，不用元婴境界作为所有参与者的唯一门槛。

| 类型 | 稳定键与准入 | 参数与结算 |
|:--|:--|:--|
| 挂机 | `idle.demon_trade_post`：魔界贸易许可 | 8h；灵石 80–130、魔界贸易站名望 +3、图鉴线索；超时保底灵石 40 |
| 挂机 | `idle.beast_habitat_watch`：妖界贸易许可 | 8h；灵米/灵叶、妖界贸易站名望 +3；不产妖血/血脉物 |
| 派遣 | `dispatch.boundary_caravan`：界隙许可、2–5 人确认或 NPC 合同 | 6h；灵石 300–500、信誉 +3；风险 failed 返 50% 可返货物，无跨界材料 |
| 派遣 | `dispatch.demon_relief` / `dispatch.beast_relocation` | 4h；常规药材/食物交付，地区名望 +6、图鉴故事线索 |
| 图鉴 | `codex.place.demon_market`、`codex.place.beast_hills`、`codex.route.boundary` | 三界路线 3 条：世界名望 +10、派遣任务额外展示 1 条 |
| 试炼塔 | `tower.three_realms` 1–20：元婴 L1 或三界许可 | 体力 12；每周每层 2 次；首通材料/图鉴/故事线索，禁止神魂晶/突破物 |
| 竞技场 | `arena.three_realms`：元婴 L1、许可匹配 | 同阵营/跨阵营只改变战术环境，不转移声望/物品；赛季 28 天 |
| 剧情 | `story.three_realms.oath` | 玄天调停/魔界契约/妖界共生三条互斥线；结局给地区名望、故事图鉴、服务权限，不改阵营战斗数值 |

跨界对局、塔和派遣都保存盟约、地区名望、污染/血脉状态快照；失败不改变境界，不把阵营故事选择强制为永久道途。