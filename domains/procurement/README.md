# procurement｜采购和供应商

**本域是相关业务对象的唯一事实所有者，不依赖 BSV1/2/3 的行政组织结构。**

- 主管对象 ID：`supplier_id, purchase_order_id, receipt_id`
- 业务事实：门店采购及中央采购共用供应商和采购事实
- 不可违反：BSV1门店采购与BSV2集中采购差别在场景，不分表
- 状态：`SCHEMA_NOT_VERIFIED`。不得把此说明自动转化为 `CREATE TABLE` 并写入现有库。
- 真实表名、主外键、约束与权限，以 Codex 实际只读盘点的 CloudBase schema 为准。任何新表必须先更新 `config/data-ownership.json`、`contracts/` 和迁移计划。
