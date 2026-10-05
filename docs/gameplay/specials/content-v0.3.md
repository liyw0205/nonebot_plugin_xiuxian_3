# v0.3 特色玩法内容基线：三界发现与异界派遣

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.3`，`rule_version=specials-0.3.0`。三界特色玩法使用许可、地区名望和快照，不用元婴境界作为所有参与者的唯一门槛。

| 类型 | 稳定键与准入 | 参数与结算 |
|:--|:--|:--|
| 挂机 | `idle.demon_trade_post`：魔界贸易许可 | 8h；灵石 80–130、魔界贸易站名望 +3、图鉴线索；超时保底灵石 40 |
| 挂机 | `idle.beast_habitat_watch`：妖界贸易许可 | 8h；灵米/灵叶、妖界贸易站名望 +3；不产妖血/血脉物 |
| 派遣 | `dispatch.boundary_caravan`：界隙许可、2–5 人确认或 NPC 合同 | 6h；灵石 300–500、信誉 +3；风险 failed 返 50% 可返货物，无跨界材料 |
| 派遣 | `dispatch.demon_relief`：有效 `permit.demon_trade`；消耗止血草 2、粗糙灵米 2 | 4h；每日 3 次；成功给魔渊集市名望 +6、魔界救援线索；部分成果只给名望 +3；失败各返还 1 份材料 |
| 派遣 | `dispatch.beast_relocation`：有效 `permit.beast_trade`；消耗灵叶 2、粗糙灵米 2 | 4h；每日 3 次；成功给三界贸易口名望 +6、妖界迁徙线索；部分成果只给名望 +3；失败各返还 1 份材料 |
| 图鉴 | `codex.story.dispatch_demon_relief`、`codex.story.dispatch_beast_relocation` | 对应派遣 success 首次发现；只记录线索，不代表完成故事或悬赏 |
| 图鉴 | `codex.place.demon_market`、`codex.place.beast_hills`、`codex.route.boundary` | 三界路线 3 条：世界名望 +10、派遣任务额外展示 1 条 |
| 试炼塔 | `tower.three_realms` 1–20：元婴 L1 或 `story.mainline.three_realms` 许可旗标 | 单人；每次体力 12；每角色/层/UTC 周最多 2 次；首通灵石 60、阵砂 2 和楼层图鉴；10/20 层另发现阵营故事线索；禁止神魂晶/突破物 |
| 竞技场 | `arena.three_realms`：元婴 L1、`item.permit.three_realms_arena`（或等价许可旗标）匹配 | 同阵营/跨阵营只改变战术环境，不转移声望/物品；赛季 28 天 |
| 剧情 | `story.three_realms.oath` | 玄天调停/魔界契约/妖界共生三条互斥线；结局给地区名望、故事图鉴、服务权限，不改阵营战斗数值 |

跨界对局、塔和派遣都保存盟约、地区名望、污染/血脉状态快照；失败不改变境界，不把阵营故事选择强制为永久道途。

两条派遣均冻结许可编号/到期时间、材料成本、风险结果、奖励及 `content-0.3` / `specials-0.3.0` 快照。风险池为 success 7000 bp、partial 2000 bp、failed 1000 bp；partial 不发图鉴线索，failed 返还每种投入材料 1 份。领取派遣许可和结算派遣均使用 operation 幂等；派遣结算写入 `specials.dispatch.settled` 来源事件。

## `tower.three_realms` 第一阶段合同

- 只开放 1–20 层单人挑战；命令为 `三界塔`、`挑战三界塔 <1-20>`、`领取三界塔奖励`。21–40 层属于 v0.4，双人挑战暂不开放。
- 元婴 L1 及以上可入场；低于该境界时，只有已完成三界主线并持有 `story.mainline.three_realms` 旗标才可入场。门槛在开始事务重新核验。
- 每次扣 12 体力；每角色、每层、每 UTC 周最多 2 次，失败计次。战斗启动失败退还体力且不计次。每层首通必须按顺序胜利并领取；同层后续胜利按练习处理。
- 首通每层奖励灵石 60、阵砂 2，并在领奖事务首次发现 `codex.challenge.three_realms.floor_N`。重复练习只得阵砂 0–1，并按观察 operation 写入同层图鉴；不发首通事件或故事线索。
- 第 10、20 层首通领奖另发现 `codex.story.three_realms.faction_<faction>`。阵营由服务端从角色快照解析；不得由命令参数选择或改写故事线。两层为首领，敌人快照按阵营使用对应稳定敌人键。
- 战斗域普通奖励为空；塔领奖是唯一资产发放点。任何结果不得产生修为、神魂晶、突破材料、境界变化、阵营声望或其他玩家资产转移。
- 1–20 层记录固定使用 `content-0.3` / `specials-0.3.0`；塔运行、结算、图鉴和领奖均以角色、楼层和 operation 唯一，并冻结阵营/盟约/污染/血脉观察快照。
