# v0.5 社交内容基线：虚空堡垒与生产联盟

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.5`，`rule_version=social-0.5.0`。宗门等级上限扩展到 6、成员上限 120；普通副本队伍仍最多 5，跨服宗门战报名 30、实际出战 15。

| 内容键 | 前置/成本 | 状态/效果 | 失败/过期 |
|:--|:--|:--|:--|
| `building.void_fortress` | 等级 5、锚 20、灵石 10000 | 48h 建造；开放跨服战/堡垒委托 | 维护不足 inactive，不拆毁 |
| `building.void_beacon` | 堡垒 active、锚 10、阵砂 30 | 24h；宗门航道成本 -1（最低 1） | 每周维护锚 2 |
| `social.alliance_contract` | 双方宗主确认、等级 5、7 天 | 共享最多 3 项配方研究进度，不共享资产/仓库 | 提前解除违约费 10000 灵石 |
| `sect.cross_server_war` | 堡垒 active、报名费 5000 公共钱包 | 周赛，30 报名/15 出战 | 资格/报名失败不扣个人资产 |

跨服战积分：占点 +10/分钟、击败 +5、摧毁战争机关 +30；同目标反刷按每轮 3 次限制。前 3 宗门获得虚空晶 10/6/3（公共奖励箱），所有实际出战成员得虚空功勋 20。公共奖励箱必须由宗主/副宗主按审计化分配，7 天后未分配物品原样保留，不自动吞没。

联盟确认窗口 24h；任一方拒绝/超时无费用。联盟研究每周最多同步 3 项，仅同步 `recipe_key` 解锁标记，不同步熟练度、材料、订单、金币或终局进度。错误：`SECT_FORTRESS_REQUIRED`、`ALLIANCE_CONFIRMATION_EXPIRED`、`ALLIANCE_RESEARCH_WEEKLY_CAP`、`CROSS_SERVER_ROSTER_CAP`。关闭后不新签联盟/报名，旧合同到期自然结束。验收：双宗主确认；违约费一次；研究不共享资产；积分抗刷；公共奖励可审计恢复。