# 社交域：关系模型

`Sect`：宗门键、名称、创建者、状态、成员上限、仓库、洞天、贡献规则和版本。

`SectMember`：宗门、玩家、职位、贡献、加入时间、成员状态和最近行动。

`SectWarRound`：轮次键、报名窗口、战斗窗口、领奖截止、状态、胜方和冻结榜单快照。首版每周两轮，
每轮 30 分钟；轮次查询、状态推进和结算均可由读写请求恢复，不依赖常驻 job。

`SectWarRegistration`：轮次、宗门、报名 operation、报名费、报名状态和宗门/成员快照。宗门等级至少 4，
报名费 2000 宗门灵石；宗主报名时最多冻结 10 名 active 成员，报名 operation 重放不重复扣费。

`SectWarMember` / `SectWarAction`：实际出战成员快照、个人贡献以及来源 operation、行动类型和分值。
占点/击败/运输/维修分别为 10/5/15/15 分；来源必须属于角色，同一来源在同一轮次只能计分一次。

`SectWarClaim`：轮次、角色、领奖 operation、奖励快照、领取/自动发放状态和时间。贡献达到 20 的成员得
世界功勋 30；胜方宗门得宗门功勋 100；领奖窗口为战斗结束后 24 小时，逾期合格奖励自动发放。

`SocialLink`：发起方、接受方、关系类型、状态、邀请过期、贡献、冷却和规则版本。

当前运行时将师徒关系落在 `mentor_relations`：保存师傅/徒弟身份、邀请状态、过期时间、接受与
毕业时间、毕业 operation 和师傅贡献快照；毕业奖励通过同一事务写入 `player_reputations`，
不会修改修为、突破材料或突破概率。

`Party`：队伍类型、队长、成员序列、地点、准备状态、当前会话、掉线时间和分配规则；当前类型为
`party.exploration_pair`（最多 2 人）、`party.arena_trio`（最多 3 人）、`party.standard_pve`（4–5 人普通副本）、
`party.boundary_realm`、`party.demon_realm` 或 `party.beast_realm`（后三者均为 2–5 人跨界副本队伍）。

`PartyBattleSession`：独立于单人 `BattleSession` 的队伍战斗 ID、队伍快照、敌人/地点/规则版本、
行动序号、状态和结果。`PartyBattleMember` 在战斗开始时保存每名成员属性/装备快照并锁定资产；
结算后释放锁。`PartyBattleReward` 以 `(battle_id, player_id)` 唯一键记录每名成员的奖励，
任一已确认成员可触发结算，但同一成员不会重复发奖。

`ThreeRealmsArenaSnapshot`：`arena.three_realms` 的个人防守快照，保存元婴 L1/许可校验结果、阵营、盟约、污染、血脉稳定、技能/装备和内容规则版本；快照进入匹配池前仍有 30 分钟延迟。三界竞技场复用竞技场对局、行动、投影和 operation 账本，保存同阵营或跨阵营战术环境；该环境不产生阵营声望、物品或玩家间资产转移。

`ServiceOrder`：委托人、服务者、服务类型、材料锁定、报价、目标品质、截止时间和交付状态。
