# quality｜安全、质量与独立督查

**本域是相关业务对象的唯一事实所有者，不依赖 BSV1/2/3 的行政组织结构。**

- 主管对象 ID：`inspection_id, finding_id, corrective_action_id`
- 业务事实：店内自检、独立督查与整改复验
- 不可违反：BSV2独立复核不可自审自批，重大风险触发停用
- 状态：`SCHEMA_NOT_VERIFIED`。不得把此说明自动转化为 `CREATE TABLE` 并写入现有库。
- 真实表名、主外键、约束与权限，以 Codex 实际只读盘点的 CloudBase schema 为准。任何新表必须先更新 `config/data-ownership.json`、`contracts/` 和迁移计划。
