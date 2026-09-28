# v0.5 冒险内容基线：虚空悬赏、航道秘境与炼虚主线

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.5`，`rule_version=adventures-0.5.1`。虚空冒险分为真实航行和服务/补给入口；未满足炼虚的角色只能参加后者。

| 类型 | 稳定键/准入 | 参数与奖励 |
|:--|:--|:--|
| 悬赏 | `bounty.void_supply`：虚空补给许可 | 交付普通补给 5；8h；商会名望 +15、灵石 500 |
| 悬赏 | `bounty.archive_recovery`：档案许可 | 找回档案片段 3；6h；图鉴/故事线索；失败不掉虚空锚 |
| 秘境 | `instance.secret_realm.void_ruins`：2–5 人专用队伍；全员炼虚 L1、位于 `void.archive_ruins`，并托管 1 枚虚空锚 | 固定 10 节点、队长支付 50 体力；每名成员每 UTC 周 1 次；首通逐成员解锁 `access.void.time_fort`、发现 `codex.void.route_ruins` 并获得 `item.void_crystal` ×1；重复通关每人 `item.void_crystal` ×1 |
| 秘境 | `instance.secret_realm.time_fort`：时序许可、2–5 人 | 6 节点；时间风暴词缀；首通普通材料/主线旗标 |
| 主线 | `story.mainline.void_archive` | 记录者/护航者/归乡者三线各 8 关；不给虚力/虚晶/突破资格 |
| 斗法留影 | `combat.replay.v0.5` | 保留 180 天/5000 场；跨服对局只保留脱敏回放摘要 |

秘境的虚空不稳定在开始时快照；成员中途掉线不改变风险池。关闭版本后停止新真实航道实例，补给悬赏仍可按服务内容结算 7 日。

### `instance.secret_realm.void_ruins` 合同

专用队伍类型为 `secret_realm_void_ruins`，必须 2–5 名已确认成员；只允许队长从 `void.archive_ruins` 启动。所有成员均需炼虚 L1、位于该地点、拥有 1 枚 `item.void_anchor`，且不能有其他长行动、秘境或战斗资产锁。入场事务一次性扣除队长 50 体力并将每人 1 枚虚空锚转入秘境托管；虚空锚不因胜负损失，在成功、战败、过期或系统中止时都只返还一次。每位成员分别占用当前 UTC 周额度。

固定路线为：`ruins_entrance -> fractured_beacon -> void_corridor -> rift_sentinel -> archive_fringe -> unstable_storm -> anchor_field -> archive_keeper -> route_tablet -> exit_gate`。`rift_sentinel` 与 `archive_keeper` 是服务端自动队伍战，其余节点由队长按顺序推进。入场时冻结全队战斗快照、首通状态、规则/内容版本和每名队员当时是否处于 `void_instability`；不稳定成员在两场战斗中使用加强敌人快照，入场后状态变化不会改写本次风险。

通关时对每名成员分别结算：首次完成写入 `access.void.time_fort` 与 `codex.void.route_ruins`，并发放 `item.void_crystal` ×1；后续每周完成只发虚空晶 ×1。战败或 60 分钟超时不退队长体力、不释放成员周额度、不发通关奖励，但返还托管锚；只有明确的系统启动/持久化故障补偿才同时退还队长体力、释放全队周额度并返还托管锚。当前战斗或路线可由任一队员经正式命令续跑；队长独占路线推进权。所有写操作使用 operation ledger，重复 operation 回放原结果；活动关闭后拒绝新建，已开始会话按冻结快照完成或恢复。
