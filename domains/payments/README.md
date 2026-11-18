# payments｜支付与对账

**本域是相关业务对象的唯一事实所有者，不依赖 BSV1/2/3 的行政组织结构。**

- 主管对象 ID：`payment_event_id, refund_id, reconciliation_id`
- 业务事实：合规支付回调、退款、日结与支付差异
- 不可违反：只有支付机构可信回调能确认资金状态
- 状态：`SCHEMA_NOT_VERIFIED`。不得把此说明自动转化为 `CREATE TABLE` 并写入现有库。
- 真实表名、主外键、约束与权限，以 Codex 实际只读盘点的 CloudBase schema 为准。任何新表必须先更新 `config/data-ownership.json`、`contracts/` 和迁移计划。
