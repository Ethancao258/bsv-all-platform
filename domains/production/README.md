# production｜制作、预调与配送追溯

**本域是相关业务对象的唯一事实所有者，不依赖 BSV1/2/3 的行政组织结构。**

- 主管对象 ID：`batch_id, shipment_id, label_id`
- 业务事实：门店自制或中央预调、标签、批次、运输、签收
- 不可违反：出品与中央配送共享批次身份；不能跨店造重复批次
- 状态：`SCHEMA_NOT_VERIFIED`。不得把此说明自动转化为 `CREATE TABLE` 并写入现有库。
- 真实表名、主外键、约束与权限，以 Codex 实际只读盘点的 CloudBase schema 为准。任何新表必须先更新 `config/data-ownership.json`、`contracts/` 和迁移计划。
