# v0.3 生产内容基线：跨界配方与契约制作

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.3`，跨界生产默认 `rule_version=production-0.3.0`；金丹前置凝魂丹使用 `production-0.3.1`。跨界生产要求元婴、对应地点/盟约或主线；失败返还 60% 可返材料，工具额外 -1000 bp 耐久，成功产出绑定 24 小时。

| `recipe_key` | 前置/地点 | 输入 | 精力/时长 | 成功产出 | 特殊规则 |
|:--|:--|:--|--:|--:|:--|
| `recipe.pill.soul_condense` | `alchemy`、金丹 | 神魂晶 1、灵叶 3、阵砂 2 | 12 / 5 分钟 | `item.pill.soul_condense` 1 | 每日 2；绑定；基础丹炉耐久 -250 bp，质量阈值 6000；失败返灵叶 1、阵砂 1 |
| `recipe.pill.soul_restore` | `alchemy` 5、元婴、跨界炼丹房 | `item.soul_crystal` 2、`item.beast_blood` 1 | 15 / 5 分钟 | `item.pill.soul_restore` 1 | 每日 3；只用于心魔净化 |
| `recipe.weapon.boundary_spear` | `artifice` 5、元婴、界隙工坊 | `item.demon_core` 3、云铁 5、神魂晶 1 | 20 / 8 分钟 | `item.weapon.boundary_spear` 1 | 每周 1；永久绑定 |
| `recipe.array.boundary_gate` | `formation` 5、元婴、界隙地点 | 神魂晶 5、阵砂 10、灵石 1000 | 25 / 10 分钟 | `item.array.boundary_gate` 1 | 队伍跨界门 3 次，7 天过期 |
| `recipe.contract.beast_pact` | 妖修或契约分支、元婴 | 妖血 3、灵石 500 | 10 / 3 分钟 | `item.contract.beast_pact` 1 | 临时妖兽契约 24 小时，不可交易 |

质量公式增加跨界地点系数：对应世界/盟约 `+500 bp`，非对应地点 `-1000 bp`；与材料/熟练/工具/随机按 production v0.1 结构合并，最终夹断 0–10000。高阶订单不开放普通玩家委托；仅宗门受控委托可创建，委托人/生产者必须同阵营或有贸易许可。

错误：`CROSS_REALM_RECIPE_LOCKED`、`CROSS_REALM_ALLIANCE_MISSING`、`PRODUCTION_WEEKLY_CAP`、`CONTRACT_SLOT_OCCUPIED`、`BOUNDARY_GATE_CHARGE_EXHAUSTED`。关闭后 processing 订单按快照结算，绑定计时不重置。验收：地点/盟约修正正确；失败返还 60% 向下取整；契约到期自动失效但不删历史；跨界门次数唯一；周产出上限不被重试绕过。
