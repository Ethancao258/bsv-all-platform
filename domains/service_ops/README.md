# service_ops｜门店服务与执行

**本域是相关业务对象的唯一事实所有者，不依赖 BSV1/2/3 的行政组织结构。**

- 主管对象 ID：`task_id, service_event_id, incident_id`
- 业务事实：座位服务、调酒任务、清洁、开闭店、日常异常
- 不可违反：上报/执行/复核分人；任务勾选不是验收
- 状态：`SCHEMA_NOT_VERIFIED`。不得把此说明自动转化为 `CREATE TABLE` 并写入现有库。
- 真实表名、主外键、约束与权限，以 Codex 实际只读盘点的 CloudBase schema 为准。任何新表必须先更新 `config/data-ownership.json`、`contracts/` 和迁移计划。
