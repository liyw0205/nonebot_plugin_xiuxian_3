# v0.2 特色玩法内容基线：金丹扩区与首次赛季

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.2`，`rule_version=specials-0.2.0`。v0.2 新增路线、派遣和塔层；所有日常/离线收益仍不得写修为、突破率或金丹突破材料。

| 类型 | 稳定键与准入 | 参数与结算 |
|:--|:--|:--|
| 挂机 | `idle.cloud_mine_watch`：筑基 L4 或矿区名望 150 | 6h、精力 2；云铁 1–3、灵石 30–50；超时保底云铁 1；每日 1 |
| 挂机 | `idle.cloud_city_shop`：城镇名望 200 | 8h；灵石 60–100、信誉 +2；每日 1 |
| 派遣 | `dispatch.cloud_mine_survey`：筑基 L4、矿镐/委托资格 | 3h、体力 8；成功云铁 3–6/名望 +4；failed 返体力 4、工具 -100 bp |
| 派遣 | `dispatch.cloud_boat_logistics`：名望 250 | 4h、货值 <=500；灵石 120–180；延误最多 +2h；每日 1 |
| 图鉴 | `codex.place.cloud_city`、`codex.material.cloud_iron`、`codex.creature.cloud_beast` | 集齐 3 条：商会名望 +8、云城订单额外展示 1 条 |
| 试炼塔 | `tower.mist_trial` 31–45：金丹 L3 | 体力 10、每日 3；首通灵石 60、材料 2；每 5 层图鉴/配方线索 |
| 竞技场 | `arena.rank`：金丹 L1；每周 20 次 | 赛季 14 天，积分规则沿用 v0.1；前 100 只得名望/称号/服务资格 |
| 剧情 | `story.cloud_city.contract` | 在商会、矿区、云舟三支中选一；结局给地区名望 15、设施外观、许可线索，不给金丹材料 |

`season.arena.foundation.<season_id>` 排序：积分 desc、胜率 desc、首次到达积分 asc、player ID asc。奖励按排名唯一：1–3 名为称号/名望 30，4–100 名为展示徽记/名望 10；无灵石、修为、装备或突破材料。关闭后既有快照与排名按赛季版本冻结。