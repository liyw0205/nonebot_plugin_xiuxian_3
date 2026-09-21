# v0.6 适配器内容基线：终局通知与只读结局令牌

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.6`，`rule_version=adapters-0.6.0`。

终局输出必须包含文本摘要、可选按钮和结局编号；默认不显示平台用户 ID。`ending.view` 只接受只读 token（角色、ending ID、过期、签名），不会调用写用例。`ending.confirm` 只能由 application 发出的单次确认 payload 调用，绑定角色快照、ending key、season key、10 分钟过期；重复点击返回已有结局摘要。

终局天榜通知每 10 分钟按 scene 批量，单批最多 50 条、每场景每轮最多 1 条。失败进入 `ENDING_NOTICE_PENDING` 审计队列，最多重投 2 次通知；绝不重试 `ascension.choose_ending` operation。媒体结局展示使用公开/私密策略，私密角色不进入频道/群榜。

错误：`ENDING_TOKEN_INVALID`、`ENDING_CONFIRM_EXPIRED`、`ENDING_ALREADY_RESOLVED`、`ENDING_NOTICE_PENDING`。验收：令牌不可跨 actor；确认不可改 ending；通知失败不改资产；展示脱敏；批量限额与重复通知去重。