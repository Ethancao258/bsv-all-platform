# catalog｜商品、配方、物料定义

**本域是相关业务对象的唯一事实所有者，不依赖 BSV1/2/3 的行政组织结构。**

- 主管对象 ID：`product_id, bundle_id, material_id, recipe_version, publication_id`
- 业务事实：鸡尾酒、套餐、配方、物料字典、菜单版本、价格
- 不可违反：已导入10表优先，必须现场核实实际主键及门店字段
- 状态：`SCHEMA_NOT_VERIFIED`。不得把此说明自动转化为 `CREATE TABLE` 并写入现有库。
- 真实表名、主外键、约束与权限，以 Codex 实际只读盘点的 CloudBase schema 为准。任何新表必须先更新 `config/data-ownership.json`、`contracts/` 和迁移计划。
