# 运行基础框架

当前运行骨架位于 `nonebot_plugin_xiuxian_3/`，业务规则不依赖 NoneBot、Web
框架或 CLI。所有适配器把平台事件归一化为 `CommandContext`，再通过同一个
`XiuxianRuntime` 路由到 application 用例。

身份判断统一由 `XiuxianApplication._invoke` 调用 `contracts.validate_command_identity` 完成：
读操作只检查适配器与平台用户身份，写操作额外检查 `can_write_assets`。各功能模块不再
重复实现身份判断，只负责自己的境界、资源、地点和会话业务规则；所有文本、按钮和 Web
入口都必须经过 `XiuxianApplication` 的公开方法。

角色功能按职责拆分在 `xiuxian/player/`：`models.py` 保存用例记录，`rules.py`
保存纯规则，`use_cases.py` 负责命令编排；适配器层只做归一化、路由和消息呈现。

## 启动

```python
from nonebot_plugin_xiuxian_3 import create_runtime

runtime = create_runtime()  # 默认使用 data/xiuxian3.sqlite3
await runtime.initialize()
```

可通过 `XIUXIAN3_DATA_DIR` 指定运行数据目录，`XIUXIAN3_MAX_INFLIGHT` 控制
异步请求上限，`XIUXIAN3_DB_BUSY_TIMEOUT_MS` 控制 SQLite 锁等待时间。SQLite
使用 WAL 和短事务；`data/` 下的领域 JSON 是只读代码配置，数据库、日志和备份
仍不进入 Git。

机缘密令通过环境变量 `XIUXIAN3_REDEMPTION_CODES` 注入 JSON 数组，例如
`[{"code_key":"code.onboarding.v0.1","code":"外部密文","reward":{"item.herb.blood_grass":1}}]`。
进程配置解析后只保留密令哈希；不要把真实密令写入仓库、日志或消息。奖励键只能是普通
灵石、精力、声望或 `item.*` 物品，不能发放修为、境界、突破准备度或道契权益。

道契测试凭证需要安装可选依赖 `cryptography`，并通过 `XIUXIAN3_BILLING_PUBLIC_KEY` 配置
Ed25519 公钥。凭证由外部 billing 服务签发，核心只验签并保存摘要；支付私钥、银行卡信息和
原始凭证不进入游戏数据库。未配置公钥或验签失败时，激活返回 `BILLING_RECEIPT_INVALID`，不改变角色资产。

配置从 `data/内容清单.json` 开始加载。领域文件统一使用 `kind`、`records` 和
记录 `key`；代码通过 `runtime.content.get("item", "item.weapon.wood_sword")`
读取，不依赖中文文件名。临时测试数据目录没有清单时，内容加载器返回空配置，
不影响基础框架测试。

## 寻仙问道

适配器只需提供平台名、平台用户 ID、场景 ID 和展示昵称：

```python
from nonebot_plugin_xiuxian_3.contracts import CommandContext

context = CommandContext(
    adapter="nonebot",
    user_id="123456",
    scene_id="group:987654",
    nickname="道友",
)
created = await runtime.dispatch(context, "开始修仙")
result = await runtime.dispatch(
    context,
    "寻仙问道",
)
```

角色创建和入道是两个独立用例。发送 `开始修仙` 可附带一个不超过 7 个字的道号；
不附带时初始为 `未命名`。首次发送只登记平台身份，阶段为 `new_user`，不会生成资质或发放灵石；随后发送 `寻仙问道` 才会原子生成固定六项
资质、进入 `mortal` 阶段并发放 100 枚灵石、30 点体力、30 点精力和教学物资。没有登记角色时，`寻仙问道` 返回
`PLAYER_NOT_FOUND`。重复执行返回幂等结果，不会重复创建角色或发奖。
`我的状态`（别名 `我的修仙信息`）只读资料卡，不会改变玩家状态。发送
`修仙改名 <道号>` 可以为未命名角色首次取名；后续改名需要消耗 `item.token.rename_card`，
道号全局不可重复。适配器会把消息事件 ID作为 operation；没有事件 ID时使用请求 ID，
消息重试不会重复结算。

凡人引导按以下顺序完成，三项完成后自动进入求道者阶段：

```text
完成引导 阅读
前往近郊
完成引导 采集
返回新手城
完成引导 炼丹    # 也可以选择炼器或布阵
选择道途 体修    # 也可以选择法修、器修、魔修、妖修
选择道途 辅修 布阵
```

教学采集消耗 2 点体力并获得 1–2 株止血草；生产教学消耗 2 点精力。辅修必须同时
选择炼丹、炼器或布阵。选择道途成功后进入感气一层，并获得 200 枚灵石、基础功法
和对应试用技能；所有写入均通过 operation ledger 原子结算。

入道后开放感气的第一条成长循环：

```text
开始修炼
结算修炼
恢复修炼
晋升境界
取消修炼
恢复状态
```

`开始修炼` 会创建 10 分钟调息会话并消耗 2 点体力；结束后用 `结算修炼` 按开始时的
资质快照结算境内修为和总修为。修炼期间不能重复开始，取消会返还体力。达到下一层
门槛后必须单独发送 `晋升境界`，不会自动跳层。`恢复状态` 按每 30 分钟恢复 1 点体力
和 1 点精力，均不超过上限。

感气二层并完成教学采集后，可以发送 `前往灵泉谷`，消耗 4 点体力抵达灵泉谷。在灵泉谷
发送 `开始修炼 灵泉` 可创建 15 分钟的灵泉修炼，消耗 3 点体力，基础修为 70，使用
11500 bp 的环境倍率，每日最多 4 次。灵泉修炼同样使用开始时的资质、地点、状态和规则
版本快照，结算、取消、过期恢复和幂等语义与调息一致。准入条件不足或位置不符时不会
扣除体力，也不会创建会话。

感气 L10 混元后可先发送 `突破预览 聚气`，再用 `开始突破 聚气` 创建 3 分钟聚气突破；可
追加 `护脉` 使用聚气护脉丹。开始时扣除焦点丹 ×1、灵叶 ×3、100 灵石，结算时按开始快照
执行 8,000 bp 基础成功率和最多 +900 bp 失败保底。成功进入聚气 L1 并奖励 80 灵石、5
体力；失败保留 80% 境内修为并进入虚弱，保护丹只在失败时消耗。`恢复虚弱` 在到期后清除
状态，`恢复虚弱 提前` 消耗低阶疗伤丹 ×1 与 50 灵石，失败保底不清除。突破与修炼、生产
会话互斥；筑基突破暂返回 `CONTENT_CLOSED`。

聚气 L10 后可继续准备筑基：发送 `突破预览 筑基`、`开始突破 筑基`。筑基突破准备 5 分钟，
消耗筑基丹 ×1、阵砂 ×3、铁石 ×3 和 500 灵石；基础成功率 7,500 bp，道基质量、匹配功法
和阵法辅修会按快照增加成功率，最高 9,000 bp。成功进入筑基 L1，获得世界功勋 50 与雾隐
洞天一层凭证；失败保留聚气修为 70% 并虚弱 6 小时，筑基护脉丹只在失败时消耗，可将保留
比例提高到 85% 并缩短虚弱到 2 小时。金丹及以上突破仍关闭。

筑基阶段可使用雾隐洞天一层的正式移动会话：发送 `移动预览 雾隐洞天` 查看条件，再发送
`前往 雾隐洞天`（也支持 `前往雾隐洞天`）创建 2 分钟移动。移动开始时原子扣除 5 点体力、
10 灵石和雾隐洞天一层凭证；到达后发送 `结算移动` 写入 `cave.mist_grotto`。移动会话保存
来源、目的地、成本、凭证、内容版本和预计到达时间，重复 operation 只回放原记录。移动期间
与修炼、生产、突破互斥，条件不足不会扣除资源或消耗凭证。当前只开放雾隐洞天一层正式入口，
其他地点仍使用教学移动切片。

探索使用独立的 `exploration_sessions` 会话和 operation ledger。当前开放四种模式：
`开始探索 近郊采集`、`开始探索 短历练`、`开始探索 灵泉采集`、`开始探索 雾隐洞天探索`。
开始时按地点、境界、引导、体力和每日次数做原子校验，并冻结地点、境界、道途、资质、
随机池和规则版本；完成后发送 `结算探索`，尚未运行的会话可以用 `取消探索` 返还体力。
结果按开始时快照和 operation 编号确定性抽取，重复请求只回放原结果，不重复扣体力或发奖。
会话状态为 `created -> settled | cancelled | expired`；固定遭遇战会进入 `combat_pending`，
此状态只能稳定返回“战斗待处理”，不会抽取探索奖励，也不会启动战斗运行时。自动回合
PVE/PvP 仍等待后置战斗门槛。

探索完成后可使用悬赏域的只读/写入命令：`悬赏榜` 查看当日三条固定悬赏，
`接取悬赏 草药补给` 或 `接取悬赏 生产订单` 冻结服务端目标和进度基线，完成后发送
`领取悬赏`。每业务日每角色最多接取一条；领取在同一 SQLite 事务中发放灵石、精力、
物品并更新地方名望/服务信誉，失败、过期、重复 operation 和不同输入冲突均不会重复发奖。
训练傀儡悬赏只展示为锁定，战斗运行时开放前不会创建悬赏会话。

道历与灵木运营的首个可运行切片开放以下命令：

```text
道历问安
补录道历 YYYY-MM-DD
浇灌灵木
收获灵木
```

`道历问安` 每业务日一次，奖励 20 灵石和最多 3 点精力；连续直接问安满 7 日额外获得
1 张机缘签。`补录道历` 只能补录本月最近 3 个已过去业务日，每月最多 2 次，消耗 30
灵石并按 80% 发放奖励，不恢复连续问安。日期唯一约束优先于 operation ID，确保同日不同
请求也只结算一次。

每名角色拥有一棵灵木，每业务日可浇灌一次，消耗 2 点精力；累计 7 次进入成熟状态。
收获按 `tree.harvest.v0.1` 的 80/100/120 灵石池（25/50/25）确定性抽取，附带地方名望
和 30% 灵木种子概率。随机池键、种子摘要、实际奖励和规则版本会和 operation 一起保存，
收获后进入 24 小时冷却，重放不会重新抽取。routine 的时间统一来自 runtime 注入的 UTC
Clock。

基础机缘池通过 `机缘寻宝`、`机缘寻宝 单抽` 和 `机缘寻宝 十连` 开放。单抽消耗 50 灵石或
优先消耗 1 张机缘签，十连固定消耗 450 灵石；连续 9 次未获得稀有线索时下一抽保底，
十连至少包含一项灵品/功法线索。每次结果、消耗、保底计数和确定性种子摘要在同一事务写入，
不发放修为、突破物或终局资产。

七日入道以首次 `寻仙问道` 的业务日为 D1，发送 `七日入道` 查看七日目标状态，发送
`领取七日目标 <1-7>` 领取已完成目标。目标允许补做但不会重置起点；D5 试炼塔、D6 派遣
在依赖系统开放前显示为未开放，不会启动战斗或生成虚假奖励。

`功业录`、`领取功业 <序号>` 和 `佩戴称号 <序号>` 使用同一 routine application 入口；
首次寻仙、三次问安会投影称号，首次问安和首次完成生产可领取一次功业奖励。试炼塔、派遣、
图鉴功业仍保持关闭，称号只用于展示。

普通结算窗口为修炼结束后的 24 小时。超过窗口的会话标记为 `expired`，`结算修炼`
返回 `CULTIVATION_EXPIRED`；发送 `恢复修炼` 会使用开始时快照完成唯一一次迟到结算，
相同 operation 只回放原结果，不会重复增加修为。感气 L3/L6/L9/L10 的晋层结果还会
返回对应的道途、经营、任务和跨境预览解锁，预览不等于开启尚未实现的写入玩法。

生产使用独立订单和资产快照，并与进行中的修炼会话互斥。当前开放炼丹、炼器、布阵各一条个人配方：
`生产预览 <配方>` 只读查看材料、工具、精力、时长和每日次数；`开始生产 <配方>` 原子
锁定材料、扣除精力和工具耐久；完成后发送 `领取生产`，或在超过 24 小时后发送
`恢复生产` 按订单快照结算。质量、随机结果、失败返还、输出和版本都保存在订单快照中，
重复 operation 只回放原结果。当前炼丹教学可直接制作低阶疗伤丹；炼器和布阵配方需满足
聚气及对应辅修、材料和地点条件，尚未开放委托订单和烹饪。

角色结果文案统一使用 Markdown，并按适配器能力发送或降级，具体标题、字段、下一步
和用户语气规范见[消息与文案规范](messaging-copywriting.md)。

## 多适配器

- `adapters/nonebot.py`：可选 NoneBot 2 matcher 注册，按事件识别平台。
- `adapters/onebot.py`：OneBot V11 群/私聊事件归一化。
- `adapters/qq.py`：QQ 官方群、C2C、频道公域/私信事件归一化。
- `adapters/web.py`：供 HTTP 框架调用的无依赖门面。
- `adapters/cli.py`：供命令行和诊断脚本调用的无依赖门面。
- `adapters/message/common.py`：通用文本结果和 Markdown 降级工具。
- `adapters/message/qq.py`：QQ 普通消息与 Markdown 消息。
- `adapters/message/onebot.py`：OneBot V11 普通消息与合并转发消息。
- `adapters/message/router.py`：按 bot/event 类型选择发送器；`adapters/messaging.py` 仅保留兼容导出。

NoneBot 依赖按需安装：`pip install -e '.[nonebot,onebot,qq]'`。OneBot/QQ
角色命令共用一个 matcher，按平台事件归一化，不会重复注册命令。
NoneBot 项目通过 `nonebot.load_plugin("nonebot_plugin_xiuxian_3")` 加载插件包；
普通 Python 导入不会自动注册 matcher。

消息投递按适配器使用专用函数：

```python
from nonebot_plugin_xiuxian_3.adapters.messaging import (
    ForwardNode,
    send_onebot_v11_forward_message,
    send_onebot_v11_text_message,
    send_qq_markdown_message,
    send_qq_text_message,
)

await send_qq_text_message(bot, event, "QQ 普通消息")
await send_qq_markdown_message(bot, event, "# 境界\n\n**感气**")
await send_onebot_v11_text_message(bot, event, "OneBot 普通消息")
await send_onebot_v11_forward_message(
    bot,
    event,
    [ForwardNode("第一段"), ForwardNode("第二段")],
)
```

QQ Markdown 使用 QQ 适配器的 `MessageSegment.markdown`；OneBot V11 合并转发使用
`send_group_forward_msg` 或 `send_private_forward_msg`，目标从事件场景自动判断。
插件内普通 matcher 回复也通过同一适配器分发函数发送；不确定平台时才使用通用
`send_text_message`，避免把 QQ 消息段发给 OneBot。

所有适配器共享 `CommandRouter`、application 和仓储；新增适配器只负责事件归一化与
结果呈现，不能复制用户创建或奖励逻辑。

## 验证

`test/test_framework.py` 覆盖重复并发注册、多适配器共用应用服务和 120 用户突发
请求。SQLite 写入失败会转换为可重试的稳定错误码，不向适配器泄漏数据库细节。
