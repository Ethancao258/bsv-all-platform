# commerce｜订单、报价与预约

**本域是相关业务对象的唯一事实所有者，不依赖 BSV1/2/3 的行政组织结构。**

- 主管对象 ID：`order_id, quote_id, booking_id`
- 业务事实：POS订单、线上订单、订单行价格快照、预约
- 不可违反：线上下单与线下点单同一订单事实，不双写
- 状态：`SCHEMA_NOT_VERIFIED`。不得把此说明自动转化为 `CREATE TABLE` 并写入现有库。
- 真实表名、主外键、约束与权限，以 Codex 实际只读盘点的 CloudBase schema 为准。任何新表必须先更新 `config/data-ownership.json`、`contracts/` 和迁移计划。
