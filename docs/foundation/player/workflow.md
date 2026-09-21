# 角色域：状态与流程

## 状态机

```text
new_user --player.start_seeking--> mortal
mortal --完成三项凡人引导--> seeker
seeker --player.enter_cultivation--> cultivator + path_selected
new_user/mortal/seeker/cultivator --admin_suspend--> suspended
suspended --admin_restore--> 原状态快照
```

## 流程

1. `create_player` 创建 `new_user` 最小角色，不创建钱包、资质或道途。
2. `start_seeking` 生成一次资质快照、结算明确的新手资源并进入凡人。
3. `complete_intro` 只结算可验证的三项引导；全部完成后进入 seeker。
4. `enter_cultivation` 校验首要道途；选择 `support` 时还必须校验主辅修，成功后进入 cultivator。
5. `suspend_player` 只改变写入权限，不删除资产。

凡人允许采集、打工、拜访、基础交易和生活任务；禁止完整功法、高风险战斗和高阶地点。

具体引导键、初始资源、道途键、失败和重复 operation 语义以 [v0.1 内容基线](content-v0.1.md) 为准。