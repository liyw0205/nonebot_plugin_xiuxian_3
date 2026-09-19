# v0.4 适配器内容基线：领域战交互

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.4`，`rule_version=adapters-0.4.0`。

领域按钮：`domain:enter:<battle>:<round>`、`domain:action:<battle>:<round>:<skill>`、`domain:retreat:<battle>:<round>`。payload 必含 `domain_id`、`battle_id`、`round_no`、actor、operation、expiry、签名；战斗 round 与领域状态由 application 再校验。有效 30 秒或当前 round 结束，以先到者为准。

领域战 `ReplyPlan` 最低文本字段：领域名、`domain_charge/current_max`、当前轮次、队友/敌方领域状态、可行动作。平台支持卡片时可展示键盘/图像；不支持时按行文本，不能隐藏能量或把 `retreat` 当安全成功。

| 后端 | 目标超时 | 降级 | 失败码 |
|:--|--:|:--|:--|
| `onebot.v11` | 8 秒 | 纯文本 | `DELIVERY_TIMEOUT` |
| `qq.official` | 10 秒 | 文本按钮 | `DELIVERY_TIMEOUT` |
| `qq.guild` | 10 秒 | 文本 | `DELIVERY_TIMEOUT` |

领域战消息媒体使用 hash 缓存；引用有效期 30 秒，过期时不重发旧行动而显示当前状态。fixtures：三人队伍、能量不足、领域冲突、round 过期、发送失败后只读重试。