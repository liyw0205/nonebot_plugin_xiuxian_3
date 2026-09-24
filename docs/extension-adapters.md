# 扩展：适配器复用方案

> **兼容概览，非权威。** 开发时先读[开发文档总入口](development-guide.md)，再进入[适配器域](extensions/adapters/)；当前状态以[当前开发状态](current-status.md)为准。

## 1. 目标

修仙 3 需要支持 OneBot V11、QQ 官方适配器和 QQ 频道场景。上游魔改适配器文档中的统一事件、消息段、引用回复、主动发送、消息记录和路由索引可以复用其设计经验，必要时复用成熟实现；领域和玩法不依赖任何适配器。

## 2. 统一上下文

适配器向 application 提供统一 `CommandContext`：

- `actor_id`
- `scene`: `group`、`private`、`channel_group`、`channel_private`、`unknown`
- `group_id` 或频道 ID
- `message_id`
- `reference_id`
- 原始文本摘要和纯文本
- `to_me`
- Bot/AppID
- `MessageCapability`
- request ID 和 operation ID

无法可靠识别用户、场景或权限的事件不得进入资产写入用例。

## 3. 可以复用的上游魔改能力

### 3.1 事件补齐

QQ 官方事件可以补齐接近 OneBot 的常用字段，但统一上下文必须使用新的 xiuxian3 DTO，不把上游事件对象传入领域层。

### 3.2 消息段

统一构造：文本、图片、音频、视频、文件、Markdown、键盘和引用。消息段构造器接收 Bot 能力，不能假设所有平台都支持同一格式。

### 3.3 消息投递

建立 `DeliveryService`，负责：

- 事件回复和主动群/私聊发送。
- `message_id` 与 `reference_id` 分离。
- QQ `REFIDX` 引用回复。
- QQ `msg_seq` 分配和冲突重试。
- interaction ACK exactly-once。
- 消息记录、撤回、广播和媒体投递。
- 成功、待审核、拒绝、可重试失败和永久失败的统一结果。

### 3.4 能力降级

- Markdown 不可用：降级纯文本。
- 键盘不可用：保留文本和 Markdown，移除键盘。
- 媒体不可用：返回文本链接或可读失败提示。
- 引用不可用：降级普通回复。
- 任何降级不能重新执行应用用例或重复发放资产。

### 3.5 命令路由

如果命令量较大或使用空前缀，可以采用上游 `on_compat` 的索引思想：按完整命令、字面前缀、正则前缀和通用 matcher 分类，先筛选可能命中的 matcher。

约束：

- 不能改变 NoneBot 原生命令语义。
- 无法安全分析的正则保留通用处理。
- `on_message` 不被命令索引误过滤。
- QQ mention、引用段和前导空文本处理在适配器入口完成。
- 路由索引重建和重复安装必须幂等。

## 4. 消息通道

业务输出 `ReplyPlan`，包含：标题、正文、键值、状态、导航动作、媒体和引用意图。Presenter 决定 Markdown、代码框、文本或键盘，不让领域层拼接平台格式。

建议状态语义：成功、可做、冷却、进行中、失败、不足和未开启。具体展示字符可以在主题配置中调整。

## 5. 事件去重和生命周期

事件去重键至少包含适配器、Bot、场景、消息 ID 和事件类型。好友、群、频道加入/离开、成员离开和 interaction 生命周期事件走独立处理，不混入普通命令限流。

## 6. 复用落地方式

推荐顺序：

1. 先实现 xiuxian3 的 `CommandContext`、`ReplyPlan` 和 `DeliveryService` 接口。
2. 将上游魔改兼容层作为候选后端适配，隔离在 `adapters/nonebot/compat` 或 vendored 目录。
3. 记录上游仓库、commit/tag、许可证、本地修改和已知限制。
4. 用 OneBot、QQ、频道 fixture 验证事件、引用、媒体、键盘和降级。
5. 通过 feature manifest 激活，不在 import 时注入全局状态。

## 7. 禁止事项

- 领域层导入 NoneBot Event、Bot、Message 或上游兼容模块。
- 业务代码直接调用 `send_group_msg`、`send_private_msg`、QQ 专有接口。
- 把平台的 message ID 当成跨平台 reference ID。
- 让适配器自动重试资产用例。
- 在适配器层复制修炼、战斗、交易和奖励规则。

## 8. 验收

每个新命令至少验证文本命令、按钮回调、OneBot、QQ 官方、私聊/群聊、能力降级、重复事件、发送失败和无权限路径。适配器回归不需要真实 token。

## 9. 实现合同

### 9.1 DTO 定义

```python
CommandContext(
    actor_id: str,
    scene: str,
    group_id: str | None,
    message_id: str | None,
    reference_id: str | None,
    plain_text: str,
    to_me: bool,
    bot_id: str | None,
    capabilities: MessageCapability,
    request_id: str,
)
```

`ReplyPlan` 至少包含状态、文本、结构化键值、导航动作、媒体引用、引用意图和降级策略。application 只接收/返回 DTO，不接收平台对象。

### 9.2 投递契约

```text
deliver(context, reply_plan) -> DeliveryResult
```

`DeliveryResult` 状态为 `sent`、`pending_audit`、`rejected`、`retryable_failure`、`permanent_failure`，并包含 message ID、reference ID、平台响应摘要和可重试标记。

投递服务不得调用资产 application 用例；发送失败不能让调用方重新执行原资产 operation。

### 9.3 投递状态机与错误语义

```text
requested -> rendering -> sending -> sent
                              |\-> pending_audit
                              |\-> rejected
                              |\-> retryable_failure -> retrying -> sent/rejected
                              \-> permanent_failure
```

适配器错误统一映射为 `ADAPTER_EVENT_INVALID`、`ADAPTER_SCENE_UNKNOWN`、`DELIVERY_CAPABILITY_MISSING`、`DELIVERY_TIMEOUT`、`DELIVERY_RATE_LIMITED`、`DELIVERY_REJECTED`、`DELIVERY_PERMANENT_FAILURE`。只有投递层标记为 `retryable` 的错误才允许重新发送；重新发送不能重新执行原业务用例。

### 9.4 事件去重

去重键：适配器、Bot ID、场景、平台消息 ID、事件类型。重复事件返回 `duplicate=true` 和已有处理结果；没有可靠消息 ID 的事件只能进入无资产读路径或由适配器生成受限去重键。

### 9.5 适配器后端

| 能力 | OneBot V11 | QQ 官方/频道 |
|:--|:--|:--|
| 群聊回复 | 事件回复/API | 群或频道发送 |
| 私聊回复 | 私聊 API | C2C/频道私信 |
| 引用 | 消息 ID | `REFIDX`/平台引用 |
| Markdown | 平台能力或纯文本 | 能力开关、模板或纯文本 |
| 键盘 | 平台能力或移除 | 自定义键盘或移除 |
| 媒体 | URL/文件段 | 上传后 URL/媒体段 |

### 9.6 验收样例

1. OneBot 和 QQ 相同文本输入生成等价 `CommandContext`。
2. 不能引用时 `ReplyPlan` 降级普通文本，不重复调用 application。
3. QQ `msg_seq` 冲突只在投递层重试，调用方 operation 不重试。
4. 重复 interaction 只确认一次 ACK。
5. 无法识别场景的事件不能修改玩家、订单或奖励。
