# v0.3 物品内容基线：元婴与三界材料

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.3`，`rule_version=items-0.3.0`。少量 `heaven` 品阶物品开放，但全部为绑定实例，不能通过自由交易绕过跨界准入。

| `item_key` | 类型/堆叠 | 绑定/交易 | 用途与限制 | 来源 |
|:--|:--|:--|:--|:--|
| `item.pill.soul_condense` | 突破丹，9 | 绑定 | 元婴突破必需；成功/失败均消耗 | 金丹炼丹辅修个人生产（`recipe.pill.soul_condense`） |
| `item.pill.soul_restore` | 心魔丹，9 | 绑定 | 仅 `heart_demon.purify` 消耗；降低疲劳/污染 | 心魔试炼、炼丹 |
| `item.soul_crystal` | 神魂材料，99 | 可交易 | 元婴突破、神魂技能、多人副本复活 | 金丹深渊门备材、跨界秘境 |
| `item.demon_core` | 魔界材料，99 | 可交易，首次获得绑定 24h | 元婴突破替代材料、魔修契约、高阶炼器 | 金丹深渊门备材、魔渊 |
| `item.clue.demon_contract` | 魔界契约线索，99 | 绑定 | 解锁契约线索展示，不直接产出契约 | 魔渊额外事件池 |
| `item.clue.beast_bloodline` | 妖界血脉线索，99 | 绑定 | 解锁血脉线索展示，不直接产出契约或稳定度 | 万兽山额外事件池 |
| `item.beast_blood` | 妖界材料，99 | 可交易，首次获得绑定 24h | 元婴突破替代材料、血脉觉醒 | 万兽山 |
| `item.weapon.boundary_spear` | heaven 法器，唯一 | 绑定 | 伤害 +80、领域能量上限 +10；耐久 10000 bp | 阵营战争周奖励 |
| `item.armor.soul_robe` | heaven 防具，唯一 | 绑定 | 神魂上限 +20、心魔抗性 +800 bp | 心魔试炼 |
| `item.token.rebuild_path` | 剧情令牌，1 | 永久绑定 | 元婴道途重构确认必需 | 三界主线唯一奖励 |
| `item.array.boundary_gate` | 阵法实例，唯一 | 宗门/队伍绑定，7 天 | 队伍跨界门 3 次；每次由队长发起 | `recipe.array.boundary_gate` |
| `item.contract.beast_pact` | 契约，唯一 | 绑定 24h | 临时妖兽协助；不进入宠物/装备系统 | `recipe.contract.beast_pact` |

## 奖励池、锁定与失败

`loot.demon.abyss.v0.3` 与 `loot.beast.hills.v0.3` 在会话开始时按地点、队伍、阵营和版本冻结；魔渊额外池按魔核 45、声望 30、契约线索 15、心魔 10 抽取，万兽山额外池按妖血 45、声望 30、血脉线索 15、祖灵事件 10 抽取，其中两个线索均为绑定堆叠展示物，未开放事件不发资产。`demon_core`/`beast_blood` 的首次 24 小时绑定写入实例/批次，不允许通过拆分堆叠绕过。`boundary_spear` 与 `soul_robe` 只能由轮次奖励 operation 发放；轮次重复领奖返回原实例引用。

道途重构 token 只在 `paths.rebuild` 确认阶段锁定，预览/取消/超时不消耗。神魂丹不能在成功元婴突破、普通修炼或任意管理员快捷操作中消耗。

错误：`CROSS_REALM_ITEM_LOCKED`、`SEASON_REWARD_ALREADY_CLAIMED`、`SOUL_ITEM_CONTEXT_INVALID`、`ITEM_BINDING_ACTIVE`。关闭 v0.3 后停止新跨界掉落，已运行会话按快照结算；绑定计时继续，不能因版本关闭解除。验收：三界材料替代条件互斥清楚；心魔丹仅净化扣除；赛季奖励唯一；绑定到期不改变历史来源；重构 token 不可交易/重复消耗。
