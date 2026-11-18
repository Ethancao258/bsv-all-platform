# identity_access｜身份、设备与访问控制

**本域是相关业务对象的唯一事实所有者，不依赖 BSV1/2/3 的行政组织结构。**

- 主管对象 ID：`auth_subject_id, role_id, grant_id, device_id`
- 业务事实：登录映射、角色、权限、作用域、审批
- 不可违反：密码/Token只归认证平台，不进入Git和业务表
- 状态：`SCHEMA_NOT_VERIFIED`。不得把此说明自动转化为 `CREATE TABLE` 并写入现有库。
- 真实表名、主外键、约束与权限，以 Codex 实际只读盘点的 CloudBase schema 为准。任何新表必须先更新 `config/data-ownership.json`、`contracts/` 和迁移计划。
