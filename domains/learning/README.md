# learning｜课程、考试与岗位资格

**本域是相关业务对象的唯一事实所有者，不依赖 BSV1/2/3 的行政组织结构。**

- 主管对象 ID：`course_id, exam_id, attempt_id, credential_id`
- 业务事实：学习进度、考试、实操认证、有效期
- 不可违反：基础权限可规则化授予；高风险权限需审批
- 状态：`SCHEMA_NOT_VERIFIED`。不得把此说明自动转化为 `CREATE TABLE` 并写入现有库。
- 真实表名、主外键、约束与权限，以 Codex 实际只读盘点的 CloudBase schema 为准。任何新表必须先更新 `config/data-ownership.json`、`contracts/` 和迁移计划。
