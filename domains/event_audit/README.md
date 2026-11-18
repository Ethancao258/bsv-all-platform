# event_audit｜事件、审计、发布和同步

**本域是相关业务对象的唯一事实所有者，不依赖 BSV1/2/3 的行政组织结构。**

- 主管对象 ID：`audit_event_id, sync_event_id, schema_version_id`
- 业务事实：不可覆盖的事件、版本、设备同步、数据谱系
- 不可违反：CloudBase官方迁移历史是DDL唯一账本，禁止另建竞争迁移表
- 状态：`SCHEMA_NOT_VERIFIED`。不得把此说明自动转化为 `CREATE TABLE` 并写入现有库。
- 真实表名、主外键、约束与权限，以 Codex 实际只读盘点的 CloudBase schema 为准。任何新表必须先更新 `config/data-ownership.json`、`contracts/` 和迁移计划。
