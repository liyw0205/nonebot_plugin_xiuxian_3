# v0.4 世界地点内容基线：领域深层与界壁门户

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.4`，`rule_version=world-0.4.0`。所有地点要求化神；进入时保存领域、宗门、阵营和环境快照。

| `location_key` | 准入 | 耗时/成本 | 行动与环境 | 关闭/退出 |
|:--|:--|:--|:--|:--|
| `cave.ancient_domain` | 化神、`item.domain_core` 1、领域未裂 | 10 分钟 / 25 体力、核心在会话后消耗 | 领域材料、远古首领；领域能量消耗 -10% | 关闭后允许撤离；未创建探索不消耗核心 |
| `demon.abyss_depths` | 化神、魔界声望 `>=3000`、污染 <90 | 10 分钟 / 25 体力、15 污染 | 深层魔核、宗门战场；`risk=extreme` | 污染达到 100 强制返回并触发心魔 |
| `beast.ancestral_lake` | 化神、妖界声望 `>=3000`、血脉稳定 >=50 | 10 分钟 / 25 体力 | 祖灵血、祖灵事件；妖修环境 +1000 bp | 稳定掉至 0 强制返回，装备不掉落 |
| `xuantian.domain_front` | 化神、宗门等级 >=4、领域已选 | 5 分钟 / 20 体力 | 三界领域争夺；每轮 30 分钟 | 非活动轮次拒绝不扣费 |
| `void.portal` | 化神、完成 `quest.break_void_intro` | 3 分钟 / 10 体力、世界功勋 100 | 虚空航道前置、界壁试炼 | v0.4 只开放试炼，不可进入虚空路线 |

领域前线每个 4 小时 UTC 活动窗口切成 8 个 30 分钟轮次，按 `event.domain_front.<round_id>` 固定领域、目标、贡献和奖励池；每宗门每轮最多 20 人加入，超出返回 `EVENT_PARTICIPANT_CAP`。领域冲突按 paths v0.4 结算，不因离开地点重置已保存战斗快照。

错误：`DOMAIN_REQUIRED`、`DOMAIN_CRACK_ACTIVE`、`POLLUTION_TOO_HIGH`、`BLOODLINE_STABILITY_LOW`、`SECT_LEVEL_INSUFFICIENT`、`EVENT_NOT_ACTIVE`。关闭时停止新进入，领域前线在当前轮次结束后结算，深层地点角色可走 `world.return_to_safe_zone`：10 分钟、体力 5。验收：领域核心只在会话创建后消耗；污染/稳定强制返回一次；宗门人数上限并发安全；门户不提前创建虚空航行会话。
