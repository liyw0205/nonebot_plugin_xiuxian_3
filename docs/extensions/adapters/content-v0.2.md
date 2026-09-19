# v0.2 适配器内容基线：资产按钮、命令索引与交互 ACK

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.2`，`rule_version=adapters-0.2.0`。所有资产写入口必须同时有文本与按钮 fixture，二者调用相同 application DTO/use case。

## 1. 路由合同

| `route_key` | 文本入口 | 按钮 payload | 写入 | 必填 payload |
|:--|:--|:--|:--|:--|
| `player.profile` | `我的修仙信息` | `profile:view` | 否 | request/player/expiry |
| `progression.cultivate` | `修炼 <mode_key>` | `cultivate:start:<mode>` | 是 | request/player/operation/mode/expiry |
| `exploration.start` | `历练 <mode_key>` | `explore:start:<mode>` | 是 | request/player/operation/mode/expiry |
| `battle.action` | `战斗 <skill> <target>` | `battle:action:<battle>:<round>:<skill>` | 是 | request/player/operation/battle/round/skill/expiry |
| `market.list` | `摆摊 <item> <qty> <price>` | `market:list:<item>` | 是 | request/player/operation/item/qty/price/expiry |

所有 payload 采用 URL-safe JSON + 版本 + HMAC；最大 512 bytes。`operation_id` 由服务器生成并绑定 payload，文本入口由 application 生成同等稳定的 operation；客户端传入自定义 operation ID 不被信任。资产按钮有效 60 秒，战斗动作有效至当前 round 结束，过期只提示重新读取状态。

## 2. Interaction ACK 与消息能力

QQ interaction ACK 使用 `ack_id` 去重，状态 `received -> acknowledged -> routed`；相同 `ack_id` 只 ACK 一次，后续返回已处理摘要。ACK 成功不表示玩法成功，真正结果由 application/operation 返回。OneBot 没有 ACK，使用事件去重和 reply message ID。

完整命令/字面前缀建立索引；正则/通用消息由独立 matcher 处理，不得因索引漏掉。热重载先卸载旧 manifest 路由，再注册新 manifest；路由冲突启动失败，不让多个 matcher 获得同一命令/别名。

## 3. 安全、失败与验收

写路由先验证 actor、scene、payload 签名/过期、事件去重、限流，再调用 application；应用拒绝仍由其 error code 呈现。每用户 30/min、每场景 120/min、全局 600/min，超过返回 `RATE_LIMITED` 且不创建 operation。按钮 payload 不含 token、物品私密详情或可直接执行 SQL/路径。

验收：文本与按钮得同一成功/重复/冲突结果；ACK 重试不二次操作；路由重载数量不增加；恶意 payload/过期/错 actor 均无写入；QQ Markdown/键盘缺能力时文本降级。