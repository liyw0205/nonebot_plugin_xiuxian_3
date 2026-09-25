# v0.3 世界地点内容基线：魔界、妖界与三界战场

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。

- `content_version`：`content-0.3`
- `rule_version`：`world-0.3.0`
- 正式开放三界跨界地点；进入时创建位置/移动会话并保存盟约、声望、环境惩罚和内容版本。

| `location_key` | 准入 | 耗时/成本 | 环境/动作 | 失败与关闭 |
|:--|:--|:--|:--|:--|
| `demon.abyss_market` | 元婴、魔界声望 `>=200` | 5 分钟 / 12 体力、500 灵石 | 魔核交易、魔修契约；环境惩罚按 stats v0.3 | 非魔修默认 `-1000 bp` 环境；盟约可抵消 |
| `demon.fallen_ruins` | 元婴、完成 `quest.demon_main_1` | 8 分钟 / 20 体力、污染上限 <80 | 心魔、魔界精英、线索；`risk=high` | 污染 >=80 拒绝；失败进 `soul_exhaustion` |
| `beast.ten_thousand_hills` | 元婴、妖界声望 `>=200` | 5 分钟 / 12 体力 | 妖兽资源、血脉任务；`risk=medium` | 非妖修有环境惩罚，盟约可抵消 |
| `beast.shapeshift_sanctum` | 妖修、元婴、血脉稳定 `>=40` | 8 分钟 / 18 体力、`item.beast_blood` 2 | 化形/血脉会话 | 非妖修永久拒绝；稳定不足不耗血 |
| `cave.boundary_realm` | 元婴、三界主线、2–5 人队伍 | 10 分钟 / 30 体力、`item.soul_crystal` 1 | 多人副本、神魂材料；`risk=high` | 队伍任一不满足则整体拒绝 |
| `xuantian.war_front` | 元婴 L1、每周活动窗口 | 5 分钟 / 15 体力 | 固定战场先锋自动战、世界功勋贡献 | 窗口外 `EVENT_NOT_ACTIVE` |

## 跨界移动与队伍规则

跨界路线在开始时锁定体力、门票/材料与队伍成员，保存 `cross_realm_penalty_bp`、盟约和队伍快照。达到后才改变位置；成员掉线不改变会话，超时由队长或恢复任务结算。边界秘境要求 2–5 名在线确认成员；确认窗口 5 分钟，超时释放全部锁定资源。

地点失败不永久掉落装备。跨界战斗/探索失败按内容会话扣神魂 2000 bp、设 `soul_exhaustion` 2 小时；移动费用不返还，因为已到达地点。角色可以通过 `world.return_to_town` 离开，耗时 5 分钟、体力 5，不绕过战斗/副本锁。

## 阵营、权限与回滚

魔界/妖界声望分别计算；地点只读取对应声望与盟约，不能用灵石替代。魔修在魔界、妖修在妖界可获得对应道途修正，但仍需满足公共境界/任务；阵营不等于管理员权限。

错误：`CROSS_REALM_REQUIREMENT_MISSING`、`FACTION_REPUTATION_INSUFFICIENT`、`POLLUTION_TOO_HIGH`、`BLOODLINE_STABILITY_LOW`、`PARTY_SIZE_INVALID`、`PARTY_CONFIRMATION_EXPIRED`、`EVENT_NOT_ACTIVE`。关闭 v0.3 时停止新跨界/战场会话，已到达角色允许返回，已开始副本按创建版本完成或受控取消。验收：不同阵营声望不互换；队伍确认超时完整解锁；跨界惩罚保存后不受盟约更新影响；战场窗口外不扣体力；化形圣地严格妖修限定。
