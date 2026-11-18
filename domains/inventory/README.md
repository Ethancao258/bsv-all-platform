# inventory｜库存与调拨

**本域是相关业务对象的唯一事实所有者，不依赖 BSV1/2/3 的行政组织结构。**

- 主管对象 ID：`stock_lot_id, stock_movement_id, inventory_count_id`
- 业务事实：进出库、报损、库存盘点、门店调拨
- 不可违反：数量事实与物料主数据分离；所有调整有原因与签名
- 状态：`SCHEMA_NOT_VERIFIED`。不得把此说明自动转化为 `CREATE TABLE` 并写入现有库。
- 真实表名、主外键、约束与权限，以 Codex 实际只读盘点的 CloudBase schema 为准。任何新表必须先更新 `config/data-ownership.json`、`contracts/` 和迁移计划。
