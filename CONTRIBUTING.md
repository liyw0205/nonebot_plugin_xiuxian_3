# 贡献指南

## 提交内容

- 每次改动保持范围清楚，并同时更新受影响的公开说明、数据合同和测试。
- 不提交 `.env`、数据库、日志、备份、真实用户数据、token、外部响应或运行缓存。
- 静态游戏内容放在 `data/`；具体规则由内容解析器和实际玩法消费者读取，不在 Python 中复制一份配置表。
- 资产变化通过 application 与领域 repository 的事务完成，并保留 operation 幂等、失败回滚和恢复语义。
- QQ、OneBot、CLI 等入口共用 application，不在适配器中重写玩法规则。

## 内容与迁移

新增面向玩家的记录应包含稳定键、名称、说明、状态及完整可执行语义，并验证跨文件引用和真实来源/消费者。官方种子变更需按[发布分发约定](docs/release-distribution.md)登记 SHA-256 与 Git 来源；安装迁移必须保留自定义和未知 JSON，验载失败时恢复替换前文件。

复杂行为遵守[数据内容合同](docs/content-data-contract.md)与[通用行为合同](docs/content-development-contract.md)。不要把未实现内容写成已开放，也不要将测试夹具或模拟平台结果表述为真实平台验收。

仓库结构、运行链路与维护边界见[开发与维护指南](docs/development-guide.md)。

## 验证

根据改动执行[测试与验收](docs/testing.md)中对应的定向测试。文档变更至少运行：

```bash
python -m pytest -q test/test_documentation.py
git diff --check
```

涉及安装文档、内容 JSON 或迁移时，另运行对应的安装、内容和种子迁移测试。所有玩家可见消息遵守[消息文案规范](docs/messaging-copywriting.md)。
