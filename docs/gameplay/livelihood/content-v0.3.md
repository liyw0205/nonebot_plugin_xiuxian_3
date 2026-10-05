# v0.3 常驻经营内容基线：三界商路、族群订单与合作工坊

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.3`，`rule_version=livelihood-0.3.0`。三界内容扩展地区和供应链，不把元婴作为普通经营门槛；个人可通过地方名望、贸易许可与护送服务参与低风险商路。

## 1. 三界贸易许可

| `permit_key` | 前置/成本 | 权利 | 风险/限制 |
|:--|:--|:--|:--|
| `permit.demon_trade` | `quest.demon_intro`、魔界声望 80、灵石 500 | 接魔界低风险采购/交付单 | 7 日有效；不开放深层探索/战斗 |
| `permit.beast_trade` | `quest.beast_intro`、妖界声望 80、灵石 500 | 接妖界药材/驯养物资单 | 7 日有效；不开放祖地内容 |
| `permit.boundary_caravan` | 地方名望 >=350、信誉 >=45、完成运输 20 次 | 承接界隙护送服务 | 需要 2–5 人队伍或 NPC 护送合同 |

许可只提供订单/路线准入，不加阵营伤害、突破成功率或修为。过期只拒绝新单，已在途路线按开始快照结算。

### 1.1 贸易许可运行合同

`permit.demon_trade` 与 `permit.beast_trade` 由 `申请贸易许可 魔界|妖界` 领取。申请事务校验对应的已完成引导旗标 `quest.demon_intro` / `quest.beast_intro`、阵营声望至少 80 和灵石至少 500；成功扣除 500 灵石并写入独立许可记录，有效期为服务端时间起 7 天。重复 operation 返回原结果；同类许可仍有效时不重复扣费，过期后可重新申请。许可记录冻结内容/规则版本、成本、引导来源和声望快照；过期记录保留供审计。

`permit.demon_trade` 只解锁 `dispatch.demon_relief`，`permit.beast_trade` 只解锁 `dispatch.beast_relocation` 及 `bounty.beast_habitat`。这些许可不等同于魔界深层准入或妖界祖地许可。

## 2. 三界常驻订单

| `commission_key` | 许可/交付 | 报酬 | 地区名望 | 库存/窗口 |
|:--|:--|:--|:--|:--|
| `trade.demon_medicine` | 魔界许可；`item.herb.blood_grass` 12 | 灵石 220 | 魔界 +6、城镇 +2 | 100/日，12h |
| `trade.beast_feed` | 妖界许可；灵米饭 10、灵叶 4 | 灵石 260 | 妖界 +6、城镇 +2 | 80/日，12h |
| `trade.boundary_repair` | 界隙许可；云铁 5、阵砂 5 | 灵石 500 | 世界名望 +5、信誉 +3 | 30/周，24h |

地区名望 `local.demon.abyss_market`、`local.beast.three_realms_trade_port`、`local.boundary.station` 各上限 1000，独立于阵营声望；只能解锁该地区设施、订单和折扣。完成来源 operation 唯一，订单取消/过期不增加名望。

## 3. 合作工坊与服务信誉

`facility.coop_workshop` 前置地方名望任一 >=300、信誉 >=50、灵石 1000、云铁 10；每周维护 200 灵石。开放 3 个服务槽，可发布不需要同宗门的炼丹/炼器/布阵/运输/鉴定订单。服务等级由信誉决定：`familiar` 10、`trusted` 30、`master` 60；等级只决定可承接订单范围和押金比例，不直接修改战斗或生产质量。

争议状态：`delivered -> disputed -> evidence_locked -> settled`。交付后委托人有 12h 提出争议，证据只引用订单快照、物品实例和服务完成 operation；管理员不得凭聊天文本改写资产。无争议自动 `settled`；虚假争议不扣资产但 7 日不得发起高价值订单。

## 4. 关闭与验收

关闭 v0.3 后，许可/工坊只读，已在途商路与争议按原版本结算。验收：低境界角色可通过许可参与贸易；地区名望不等于阵营声望；一笔订单不能同时给两种名望奖励；争议与超时只结算一次；合作工坊不创建跨服或跨界突破捷径。
