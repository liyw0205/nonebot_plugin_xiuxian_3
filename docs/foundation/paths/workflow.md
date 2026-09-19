# 道途域：选择与切换状态机

```text
unselected -> selected
selected -> switch_pending -> selected
selected -> frozen -> selected
```

选择流程：检查阶段和内容开放 -> 创建道途记录 -> 激活初始被动 -> 写入选择 operation。

切换流程：生成计划 -> 展示保留/冻结/转化/清理项 -> 玩家确认 -> 锁定费用 -> 应用切换 -> 生成新属性快照。

切换确认超时不扣资源。已应用切换不能通过重复请求回滚；管理员恢复必须使用独立恢复用例。污染、血脉和契约不能通过普通洗点删除。