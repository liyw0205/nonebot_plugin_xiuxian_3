# v0.14 冒险内容基线（第十三章「万兽山·守契夜巡」）

本文件遵守[版本内容开发合同](../../content-development-contract.md)。本阶段是
`story.mainline.xuantian` 的可选剧情尾声，承接第十三章前三关的守山定契，不改变已经发布的
第九章账房夜值，也不把玄天主线末关接到化神 `story.mainline.domain_frontier`。

## 关卡与玩家流程

`chapter.13.stage.4`「守契夜巡」要求前置 `chapter.13.stage.3`、元婴 `nascent_soul` L10，
并沿用主线命令：

1. 用 `主线道途` 查看并发送 `开始主线 守契夜巡`。
2. 若当前位置不是 `beast.ten_thousand_hills`，发送 `前往 万兽山入口`，等待后发送 `结算移动`。
3. 在万兽山用 `挂机预览 万兽山守契` 检查门槛，再用 `开始挂机 万兽山守契` 安排守契夜巡。
4. 十小时完整窗口结束后发送 `领取挂机`，再发送 `领取主线奖励 守契夜巡`。

主线目标只消费本关开始之后、同一玩家、同一路线且状态为 `claimed` 的完整挂机记录。
旧安排、未结算行程、取消、逾时保底和其他玩家的记录都不推进本关；失败提示保留实际缺失的
地点、境界、体力、日限或活动状态，方便按原路线重试。

## 数据与真实消费者

| 内容 | 稳定键与规则 |
|:--|:--|
| 主线 | `chapter.13.stage.4`，`idle_claim` 目标 `idle.beast_hills_watch`，事件 `story.mainline.xuantian:chapter.13.stage.4` |
| 路线 | `idle.beast_hills_watch`，地点 `beast.ten_thousand_hills`，36000 秒、每日 1 次、体力 4，无额外声望或许可门槛 |
| 完整奖励 | `reward_pool.idle.beast_hills_watch`：灵石 160–220、`item.clue.beast_bloodline`×1、`local.beast.three_realms_trade_port` 名望 4 |
| 逾时保底 | `reward_pool.idle.beast_hills_watch.fallback`：灵石 60；不满足主线完整领取目标 |

万兽山已经是 active 地点，云舟渡口到万兽山的公开移动路线需要 300 秒和 12 点体力；本阶段
复用 `WorldTravel`、`IdleRepository`、主线 repository 与共享奖励事务，不新增 schema、路线、
物品或权限。血脉线索和三界贸易口名望均已有下游消费者，奖励不会成为孤立数据。

## 持久化、兼容与消息

挂机安排、开始时间水位、领取状态、operation ledger 和主线快照全部复用现有表与事务；宿主
重启或适配器切换后，`挂机状态` 和 `主线道途` 从数据库恢复。重复开始/领取 operation 只回放
原结果，坏快照、未知 JSON 和账本失败回滚，保留旧存档字段而不把未知内容抹成空对象。

QQ 官方和 OneBot V11 共享同一 application。QQ 帮助使用 `command_link` 提供守契夜巡、挂机
预览、开始、状态和主线领奖的蓝字/按钮；不支持 Markdown 时降级为可直接发送的文本。OneBot
使用相同命令和可诊断错误码，不由适配器复制门槛或结算规则。

本阶段不改变 `chapter.13.stage.1-.3`、`chapter.12.stage.3` 的既有前置、不新增化神入口，旧
第十三章三关存档继续可读且 `.3` 仍为主线链路终点。公开状态仅在实现、定向测试和发布包都完成
后宣称 `open`。
