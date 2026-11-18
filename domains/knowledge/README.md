# knowledge｜制度、教学资料和版本

**本域是相关业务对象的唯一事实所有者，不依赖 BSV1/2/3 的行政组织结构。**

- 主管对象 ID：`document_id, document_version_id, acknowledgement_id`
- 业务事实：SOP、课程材料、服务教程、外部链接及版权来源
- 不可违反：视频原件进入受控对象存储，Git只存元数据
- 状态：`SCHEMA_NOT_VERIFIED`。不得把此说明自动转化为 `CREATE TABLE` 并写入现有库。
- 真实表名、主外键、约束与权限，以 Codex 实际只读盘点的 CloudBase schema 为准。任何新表必须先更新 `config/data-ownership.json`、`contracts/` 和迁移计划。
