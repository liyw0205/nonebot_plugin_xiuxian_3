# 适配器域：统一 DTO

`CommandContext`：actor ID、scene、group ID、message ID、reference ID、纯文本、to_me、bot ID、能力、request ID。

场景：`group`、`private`、`channel_group`、`channel_private`、`unknown`。

`ReplyPlan`：状态、文本、键值、导航、媒体引用、引用意图和降级策略。

领域/application 不接收 NoneBot Event、Bot 或 Message。未知场景不得进入资产写入。