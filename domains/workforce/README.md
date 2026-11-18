# workforce｜员工与排班

**本域是相关业务对象的唯一事实所有者，不依赖 BSV1/2/3 的行政组织结构。**

- 主管对象 ID：`employee_id, shift_id, employment_id`
- 业务事实：员工档案、用工关系、考勤、班次、交接
- 不可违反：员工身份不等于系统角色；跨店是一人多授权
- 状态：`SCHEMA_NOT_VERIFIED`。不得把此说明自动转化为 `CREATE TABLE` 并写入现有库。
- 真实表名、主外键、约束与权限，以 Codex 实际只读盘点的 CloudBase schema 为准。任何新表必须先更新 `config/data-ownership.json`、`contracts/` 和迁移计划。
