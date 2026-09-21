# v0.4 探索内容基线：领域深层探索

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.4`，`rule_version=exploration-0.4.0`。所有模式要求化神、领域未裂；开始时冻结领域、污染/血脉、阵营、地点和奖励池。

| `mode_key` | 前置 | 时长/成本 | 保底与随机 | 风险/上限 |
|:--|:--|:--|:--|:--|
| `explore.ancient_domain` | 远古洞天、`item.domain_core` 已锁 | 20 分钟 / 25 体力 | 古果 1；`loot.domain.boss.v0.4` 额外奖励 | 领域首领 35%；每日 2 |
| `explore.abyss_depths` | 魔渊深层、魔界声望 3000、污染 <90 | 20 分钟 / 25 体力、污染 +15 | 深层魔核 1、魔界声望 30 | 深层战 40%；污染 100 强制返回；每日 2 |
| `explore.ancestral_lake` | 祖灵湖、妖界声望 3000、稳定 >=50 | 20 分钟 / 25 体力、稳定 -5 | 祖灵血 1、妖界声望 30 | 祖灵事件 35%；稳定 0 强制返回；每日 2 |

领域核心只在 `ancient_domain` 会话创建后消耗；战斗失败不重新抽古果，改为保底古果 1 + 失败记录。魔渊/祖灵湖事件采用地点池 `event.abyss_depths.v0.4` / `event.ancestral_lake.v0.4`，保存 roll、污染/稳定前后值和领域状态。

每日最多接取 3 条化神悬赏：`bounty.domain_core`（远古首领 1）、`bounty.abyss_defense`（深层战胜利 2）、`bounty.ancestral_tribute`（祖灵血 3）。奖励分别为领域核心 1、功勋 300、妖界声望 100；奖励 operation 以 offer/角色唯一。

错误：`DOMAIN_CRACK_ACTIVE`、`DOMAIN_CORE_MISSING`、`POLLUTION_TOO_HIGH`、`BLOODLINE_STABILITY_LOW`、`EXPLORATION_DAILY_CAP`。关闭时停止新会话，已运行会话可结算/由恢复任务失败结算；污染/稳定变化不回滚为 0。验收：领域裂痕无扣费；保底与随机不双发；强制返回一次；悬赏贡献重试稳定。