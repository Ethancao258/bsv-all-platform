# organization｜组织与经营主体

**本域是相关业务对象的唯一事实所有者，不依赖 BSV1/2/3 的行政组织结构。**

- 主管对象 ID：`legal_entity_id, store_id, org_unit_id`
- 业务事实：法律主体、区域、门店主身份、合作边界
- 不可违反：现有产品库可能含 bsv_stores，检查后复用，不再造第二主表
- 状态：`SCHEMA_NOT_VERIFIED`。不得把此说明自动转化为 `CREATE TABLE` 并写入现有库。
- 真实表名、主外键、约束与权限，以 Codex 实际只读盘点的 CloudBase schema 为准。任何新表必须先更新 `config/data-ownership.json`、`contracts/` 和迁移计划。
