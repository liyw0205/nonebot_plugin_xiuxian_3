# v0.4 特色玩法内容基线：领域观察与三界重建

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.4`，`rule_version=specials-0.4.0`。领域特色玩法的个人参与资格可由地区名望/公共项目取得；化神领域只提供路线效率或观察选项，不把领域核心、化神材料或领域能量当作派遣/挂机奖励。

| 类型 | 稳定键与准入 | 参数与结算 |
|:--|:--|:--|
| 挂机 | `idle.domain_refuge_watch`：参与 `project.domain_refuge` >=10 点 | 10h；灵石 100–160、建设券 1、避难所名望 +3；超时灵石 50 |
| 派遣 | `dispatch.domain_reconstruction`：地区名望 450 或宗门授权 | 6h；木材/阵砂/药材服务；成功名望 +8、信誉 +3；partial 只给一半名望 |
| 派遣 | `dispatch.abyss_purification` / `dispatch.ancestral_relief` | 4h；普通材料交付；仅地区名望/图鉴线索，不产魔核/祖灵血 |
| 图鉴 | `codex.domain.*` 六条领域观察记录 | 收集 3 条：领域战术百科、居所外观；无领域能量/属性 |
| 试炼塔 | `tower.three_realms` 21–40：化神 L1 或重建名望总值 500 | 单人/双人；每次每名成员体力 12；每层每成员每 UTC 周 2 次；首通灵石 60、阵砂 2；30/40 层阵营故事图鉴；40 层展示称号；双人奖励独立领取 |
| 竞技场 | `arena.domain_spar`：化神 L1 或领域观察许可 | 中性领域模拟；每周 10 次；积分/名望/图鉴，不给领域能量 |
| 剧情 | `story.domain_rebuild` | 守界/净渊/护祖三条分支；结局给公共项目权限、地区名望 20、展示，不锁领域选择 |

塔和竞技场的领域效果为快照中的战术修正，不读取战后实际领域状态；关闭领域内容不取消正在进行的对局。

## `tower.three_realms` v0.4 扩层合同

- 仅新增 21–40 层规则；单人命令为 `三界塔`、`挑战三界塔 <1-40>`、`领取三界塔奖励`，双人命令为 `创建三界塔双人队伍`、`挑战三界塔双人 <1-40>`、`领取三界塔双人奖励`；虚空塔仍关闭。
- 门槛为化神 L1，或 `local.domain_refuge`、`local.abyss_outpost`、`local.ancestral_habitat` 的重建名望总值达到 500。v0.3 的三界主线许可只开放 1–20 层，不替代 v0.4 门槛。
- 每次扣体力 12；每角色/层/UTC 周最多 2 次，首通、练习、失败和逃跑均计次。战斗无法启动时退还全部体力且不计次。首通仍须按 1→40 层逐层胜利并领取；练习奖励由 run ID 摘要决定为阵砂 0 或 1。
- 首通每层固定领取灵石 60、阵砂 2，并发现 `codex.challenge.three_realms.floor_N`。第 30 层发现 `codex.story.three_realms.reconstruction_<faction>`；第 40 层发现 `codex.story.three_realms.domain_<faction>` 并授予展示称号 `title.three_realms_tower.domain_guardian`。故事阵营取战斗开始快照。
- v0.4 首领为第 30/40 层，敌人键分别为 `enemy.three_realms_tower.<faction>.floor_30_boss` 与 `enemy.three_realms_tower.<faction>.floor_40_boss`；21–29 层使用 `.domain_vanguard`，31–39 层使用 `.domain_veteran`。
- v0.3 的 1–20 层继续使用 `content-0.3` / `specials-0.3.0`，v0.4 的 21–40 层使用 `content-0.4` / `specials-0.4.0`。战斗普通奖励为空，领取白名单仍仅限灵石和阵砂，不产生修为、神魂晶、突破物、声望或资产转移。
双人挑战固定两名已确认同地点成员，分别冻结构筑、技能、属性、阵营/盟约、三界名望、污染和血脉；分别计周限并扣体力。失败不发奖励，战斗启动故障双方退款；双人塔运行表和成员奖励表不与单人塔或普通队伍 PVE 混用。
