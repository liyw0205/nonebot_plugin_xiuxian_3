# 工程维护说明

文档阅读入口为 [文档索引](docs/index.md)，玩家当前可用范围以[当前可用能力](docs/availability.md)和实际公开入口为准。玩法内容遵守[内容设计总表](docs/content-development.md)、[数据内容合同](docs/content-data-contract.md)及对应领域说明。

## 变更约定

- 静态内容与可调整参数维护在 `data/`；Python 实现通用执行规则，不复制内容表或隐式回退数据。
- 内容变更要验证严格解析、跨文件引用、真实来源和消费者，并按[发布分发约定](docs/release-distribution.md)登记官方种子迁移的旧/新 SHA-256 与 Git 来源。
- 资产写入通过 application 与领域 repository，在单一事务中维护 operation 幂等、流水、快照和失败回滚。
- QQ、OneBot、CLI 与 Web 入口共用 application；适配器只处理输入归一化、权限上下文和结果呈现。
- 数据库 schema 变化必须提供迁移，保留既有玩家数据；测试数据库位于临时目录或明确指定的测试路径。
- 不提交凭据、数据库、运行日志、备份、用户数据或缓存；不以跳过测试、删断言或降低门槛处理真实失败。

## 验证

按[测试与验收](docs/testing.md)选择受影响的定向验证。文档变更至少运行：

```bash
python -m pytest -q test/test_documentation.py
git diff --check
```
