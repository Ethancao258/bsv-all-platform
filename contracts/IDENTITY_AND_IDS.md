# 稳定ID与数据语义｜不得因为中文名或部门更名改变

| 权威对象 | 唯一键 | 所有权域 | 使用方 |
|---|---|---|---|
| 合法主体 | `legal_entity_id` | organization | 合同、应收付、税务、投资 |
| 门店 | `store_id` | organization | 订单、库存、员工、总部分析 |
| 员工 | `employee_id` | workforce | 考勤、岗位资格、制单操作 |
| 认证主体 | `auth_subject_id` | identity_access/平台auth映射 | 登录；不可与employee_id混淆 |
| 岗位角色 | `role_id` | identity_access | 按角色+门店+操作+有效期授权 |
| 商品/套餐 | `product_id`/`bundle_id` | catalog | 菜单、订单、配方、出品 |
| 物料/配方 | `material_id`/`recipe_version` | catalog | 库存、标签、成本、预调 |
| 生产/配送 | `batch_id`/`shipment_id` | production | 门店自制/中央配送共用追溯 |
| 交易/报价 | `order_id`/`quote_id` | commerce | POS与线上订单、价格快照 |
| 顾客/授权 | `customer_id`/`consent_id` | customer | 非强制会员与私域权益 |
| 资本审批 | `capital_decision_id` | capital | BSV3审议，不是BSV1日常费用 |

- ID 是不可变的主键，不是 `J2` 标签码、商品中文名、SKU显示码、门店名称或组织职级 L1/L2。
- 现有数据库中的键数据类型/生成方法需真实读取，不能在本包臆造 UUID/字符串格式然后强制重建。
- 历史订单保存下单时的 `name_snapshot`、`unit_price_minor`、`discount_snapshot`、`recipe_version`；改菜单不得改变已支付历史。
- 时间存UTC时刻和可审计业务时区；货币金额推荐最小单位整数，汇率注明结算日/来源。
- `store_id` 跨法律主体的归属必须是可追溯时间范围；实体和员工职位变化是关系更新，不是换主键。
