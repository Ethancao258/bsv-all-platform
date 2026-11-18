# operating_finance｜日常经营财务

**本域是相关业务对象的唯一事实所有者，不依赖 BSV1/2/3 的行政组织结构。**

- 主管对象 ID：`cost_entry_id, payroll_run_id, settlement_id`
- 业务事实：薪资、采购、房租、经营盈亏、现金流和SDF
- 不可违反：不可与BSV3可投资资本混同，来源事实需可追溯
- 状态：`SCHEMA_NOT_VERIFIED`。不得把此说明自动转化为 `CREATE TABLE` 并写入现有库。
- 真实表名、主外键、约束与权限，以 Codex 实际只读盘点的 CloudBase schema 为准。任何新表必须先更新 `config/data-ownership.json`、`contracts/` 和迁移计划。
