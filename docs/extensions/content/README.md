# 扩展：数据内容域

数据内容域负责规则包、内容包、schema、加载校验、发布、迁移和回滚。

- [内容包](content-package.md)
- [校验与发布](validation-release.md)
- [数据库迁移](migrations.md)
- [用例与验收](use-cases.md)

所有 `content-v0.1.md` 至 `content-v0.6.md` 都必须遵守
[版本内容开发合同](../../content-development-contract.md)，并在提交前执行：

```bash
python3 scripts/validate_content_docs.py
```

该校验器是发布前的最低门槛；实际内容发布还必须执行 dry-run、创建备份、原子激活和
激活后 health/read-only smoke。内容包只允许增加稳定键或显式关闭内容，不能重写已结算
operation 引用的历史定义。