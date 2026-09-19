# v0.5 适配器内容基线：虚空分页与跨服战场

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.5`，`rule_version=adapters-0.5.0`。

虚空导航 route：`void:route:<route>`、`void:node:<session>:<node>`、`void:anchor:<session>`；跨服战场：`sect:war:<war_id>:status`。所有 payload 绑定 `player_id`、`scene`、`session/battle_id`、`round/node`、`operation_id`、60 秒 expiry、签名。不同战场/会话 payload 混用返回 `WAR_SCENE_MISMATCH`/`VOID_NODE_EXPIRED`，不调用写用例。

分页最多 10 页、每页最多 8 项；媒体/大文件不能直接上传时生成数据根内的短期下载标识（10 分钟），OneBot 始终发链接，QQ/频道可按能力发文件。下载标识与 actor/permission 绑定，不能通过参数给任意路径。

多 Bot 备用策略仍至多切换一次；虚空行动发送失败仅创建 `pending_audit`，不取消或重建航道会话。验收：分页越界、跨场景按钮、过期节点、下载越权、发送失败均无资产二次写入。