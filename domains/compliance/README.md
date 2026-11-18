# compliance｜日常合规与证照

**本域是相关业务对象的唯一事实所有者，不依赖 BSV1/2/3 的行政组织结构。**

- 主管对象 ID：`license_id, policy_id, compliance_issue_id`
- 业务事实：许可证、食品安全、劳动、隐私、制度追踪
- 不可违反：许可证与主体、场所、业务活动绑定，不自动跨店继承
- 状态：`SCHEMA_NOT_VERIFIED`。不得把此说明自动转化为 `CREATE TABLE` 并写入现有库。
- 真实表名、主外键、约束与权限，以 Codex 实际只读盘点的 CloudBase schema 为准。任何新表必须先更新 `config/data-ownership.json`、`contracts/` 和迁移计划。
