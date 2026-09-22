# 运行基础框架

当前运行骨架位于 `nonebot_plugin_xiuxian_3/`，业务规则不依赖 NoneBot、Web
框架或 CLI。所有适配器把平台事件归一化为 `CommandContext`，再通过同一个
`XiuxianRuntime` 路由到 application 用例。

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
