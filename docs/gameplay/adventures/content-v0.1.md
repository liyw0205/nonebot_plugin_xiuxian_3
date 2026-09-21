# v0.1 冒险内容基线：悬赏榜、秘境试炼、主线道途与斗法留影

本文件遵守[版本内容开发合同](../../content-development-contract.md)与[冒险域](README.md)。`content_version=content-0.1`，`rule_version=adventures-0.1.0`。

## 1. 悬赏榜

| `bounty_key` | 开放/目标 | 时限/上限 | 奖励 | 失败 |
|:--|:--|:--|:--|:--|
| `bounty.herb_supply` | 凡人；交付止血草 5 | 30m；每日 1 | 灵石 30、地方名望 +2 | 过期无奖励，不回收草 |
| `bounty.training_dummy` | 感气 L1；胜训练傀儡 2 | 1h；每日 1 | 修为 120、`item.pill.focus_low` 1 | 过期无奖励 |
| `bounty.craft_order` | 完成任意生产订单 1 | 2h；每日 1 | 精力 10、服务信誉 +2 | 过期无奖励 |

每日 00:00 创建 `bounty.daily.<date>`；角色最多接 1 条。接取时冻结目标/奖励/截止时间；同一已结算事件只推进一次；领取键为 `bounty_key:date:player`。

## 2. 秘境试炼

| `instance_key` | 前置 | 路线/成本 | 首通奖励 | 重复挑战 |
|:--|:--|:--|:--|:--|
| `instance.secret_realm.mist_grotto` | 聚气 L4、`item.cave_pass_basic` 1 | 3 节点、10 体力；进入时锁票 | 灵石 80、洞天材料 2、图鉴 1 | 每周 2 次，材料 0–1 |
| `instance.secret_realm.spring_path` | 感气 L3、灵泉谷到达 | 2 节点、6 体力 | 灵叶 2、地方名望 +5 | 每日 1 次，灵叶 0–1 |

节点由服务端保存：`resource -> encounter -> choice`。玩家只能选择当前允许节点；战斗失败不重抽资源。实例状态 `entered -> routing -> combat_pending -> cleared/failed -> settled`；入场票/体力在创建时锁定，失败按定义消耗体力但不消费未使用材料。

## 3. 主线道途：`story.mainline.xuantian`

| 章节/关卡 | 前置 | 首通结果 | 重复 |
|:--|:--|:--|:--|
| `chapter.1.stage.1` 初入玄天 | 寻仙问道 | 解锁近郊、图鉴、名望 +3 | 灵石 5 |
| `chapter.1.stage.2` 灵泉取叶 | stage 1、感气 L1 或凡人采集引导 | 解锁灵泉谷、灵叶 2 | 材料 0–1 |
| `chapter.1.stage.3` 雾中守门 | stage 2、感气 L3 | 解锁秘境试炼、称号 `title.mist_watcher` | 图鉴观察 |
| `chapter.2.stage.1` 城镇委托 | 完成常驻经营任一委托 | 解锁商路、服务信誉 +5 | 灵石 10 |

首通唯一键 `story.mainline.xuantian:chapter:stage:player`；重试不重复开放地点或发放首通奖励。章节奖励不改变道途、体质或终局旗标。

## 4. 斗法留影

每场战斗结束自动写 `combat.replay`，保留 30 天或最近 100 场（取较大者）；日志保存回合、技能、目标、消耗、随机 roll、状态和结果快照摘要。默认私有，分享后生成 24h 签名只读链接；撤销分享不删除个人日志。日志读取不创建资产 operation，不显示平台 ID/完整背包/隐藏故事旗标。

## 5. 关闭与验收

关闭 v0.1 停止新悬赏/秘境/主线关卡；运行实例按原版本恢复或结算，pending 首通 7 日可领。验收：offer 刷新不改已接任务；秘境节点不能跳跃；主线首通不双发；日志只读；战斗失败不重抽秘境奖励。