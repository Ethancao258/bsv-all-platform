# BSV ALL 数据库整合预检基线 v1

本基线追溯至 BSV1 canonical handoff 3.1、菜单 V13.1、供货 V2.0 和人员身份 V2.0 R2。以已有 [数据所有权注册表](../../config/data-ownership.json) 的 66 个键（[机器交叉映射](entity-crosswalk.json)）为集团总入口。下表覆盖已交付对象及本轮有依赖的对象；注册表其余对象仍仅按既有架构归属，未发现可核实的实现时保持待核实。各部署环境的真实表须分别盘点。

[机器字段字典](field-dictionary.json) 由隔离数据库反射生成，按表包含原始类型、可空性、默认值、PK、FK、唯一约束、检查、索引和可反射的触发器。SQLite 的 TEXT ID、布尔或 UTC 存储形式不自动等于 PostgreSQL 的物理类型。此处 `UNKNOWN_G0` 表示无真实 CloudBase 见证。

## 事实与接口交叉表

| 对象与权威域 | 已实际读取的本地表或交付投影 | PostgreSQL 候选及约束 | 读接口与唯一写入责任 |
|---|---|---|---|
| 永久人员 `tr_code`、`employee_id`、`employment_id`（workforce） | POS `staff.id TEXT` 是历史旧码，`staff_store_access` 是本地授权镜像；供货临时身份来自 B；EMP/BM 由 TR 推导 | `bsv_identity_people.tr_code VARCHAR(7)` PK、不可更新/删除；allocator 单行加锁；`stage_issuances UNIQUE(tr_code,stage)`；`engagements` FK TR；`legacy_aliases UNIQUE(legal_entity_id,source_system,legacy_value)` FK TR | `/api/v1/identity/me` 和人员审批 API；仅 A 中经双人审批建立身份、关联或任职 |
| `auth_subject_id`、`role_id`、`grant_id`（identity_access），学习资格 `credential_id`（learning） | POS 会话、HQ 授权是本地试点；供货无独立员工主档 | `bsv_identity_auth_links` subject 唯一，FK TR；`auth_sessions` 按摘要、到期及撤销；`grants` 按法人/门店/动作/时间；`bm_appointments` FK TR/申请；`qualification_links.learning_credential_id` 唯一外部引用，实际 FK 待核 | CloudBase Auth 持有正式凭据；A 复核权限，POS `pos-session` 与供货 `/api/v1/auth/me`。集团组织和 learning 签发方独立 |
| 法人、门店及库位（organization），座位归属待登记 | `stores.id TEXT`、`seats.id TEXT`、`table_groups`、`bsv_layout_revisions`、`store_layout_data`。V9 T 门店码与 4 个发布快照门店码已交叉验证 | `bsv_stores` 真实存在性未知。Supply `source_location_id/dest_location_id TEXT` 预留 FK，库位不等同门店。43 个候选座位保持原值；集团尚未授权 seat_id 新所有权 | POS `/api/state`、HQ 地图审批、供货 C `/stores`；仅组织域维护法人/门店，地图由有权限的发布流程维护 |
| 商品、套餐、配方、物料、发布（catalog） | POS `bsv_products`、`bsv_v9_record`、`bsv_v9_extra`、`bsv_v9_quote`、`bsv_v9_sync`。V9 L 列稳定码，C、K、M、P、R 分开。V13.1 `bsv.public-menu.v2` 是冻结公开投影 | CloudBase 10 张表的真实列、类型、PK 与配方 FK 为 UNKNOWN。P 项集团语义映射待核；K 的公开 `product_id` 为历史 bundle 投影 | POS `/api/catalog/item`、供货 A `/items`、顾客静态 JSON。只允许 catalog 批准发布，禁止菜单反写价格或用 SKU 关联 |
| `order_id`、`quote_id`（commerce）；制作送达（service_ops） | `visits` FK 门店/座位/人员；`orders.id TEXT` UNIQUE visit；`order_lines` FK 订单/商品并保存名称与整数分；`order_drafts`、`production_tasks`、`production_finishes`、`production_deliveries` | 无已批准中央订单候选。先保留历史 ID/金额/原始操作员 ID 映射；缺实际 `recipe_version` 时列为未映射 | POS `/api/orders/submit` 等；仅订单服务入账，出品事件不得自动扣库两次 |
| `payment_event_id/refund_id/reconciliation_id`（payments） | `demo_checkouts`、`visit_closures`、`order_lines.checkout_id` 是 POS 试点记录 | 无已核实中央表。模拟结账不能转换成已到账事实；以签名/查单确认、渠道事件唯一、金额最小单位 | POS 模拟结账只供测试；付款服务经机构验签后写入，日结独立对账 |
| 供应商、采购、收货 `supplier_id/purchase_order_id/receipt_id`（procurement） | 本批未接入独立采购事实；中央配送收货不可替代门店采购和应付事实 | 真实采购和供应商表未知。候选供货 `shipment_package` 状态只表示配送收货 | 采购服务与中央 D 独立分责；门店批准的采购、自制路径继续独立 |
| `batch_id/shipment_id` 及包装（production）；流水、盘点、库存批次（inventory） | 供货 SQLite `shipments/packages/balances/movements/counts` 是隔离演示；POS 生产任务是出品执行 | `supply.shipment UUID` PK，版本整数；`shipment_package.package_id UUID`、FK shipment、正数 `NUMERIC(18,4)`；`movement` 候选 UUID/FK，`lot_id TEXT` 的生产批次/库存批次区分待核；`stock_count` 五档检查；`idempotent_result` 按 actor scope + request UUID | D `/supply/shipments`、`/inventory/balances`、`/inventory/counts`；包装防重及发/收单事务唯一写入库存，盘点仅观察 |
| 检查/整改（quality），审计（event_audit） | 供货 SQLite `inspections/inspection_kind/inspection_reviews/action_audit`；POS `audit_events/bsv_platform_events`；身份 A `bsv_identity_audit_events` | PostgreSQL `preflight_quality` 仅测试替身，review FK 检查且一检一复核。正式整改与集成审计表未知；身份审计 PG 行级触发器保护历史 | E `/inspections`；BSV1 自检与 BSV2 独立复核分开。本人或被检查人不能批准自己涉及的复核。审计追加，无普通更改权限 |
| 离线同步 `sync_event_id`（event_audit） | POS `command_dedup` 为本地防重。供货 `offline_cache.sqlite3.pending/snapshots` 是按员工/权限范围暂存和读取缓存 | 无已验收 POS 上传消费者或公司 Outbox。`supply.idempotent_result` 只是候选中央去重表 | 供货 `/api/pending/sync` 重验身份并沿用原请求，只有主库确认才提交；接口与集团 Outbox 实际结构待 G0 |

## 可核实冲突

1. POS 历史员工 ID、身份永久 TR、派生 EMP 显示码和平台认证 subject 是四个不同字段。审批过的法人旧码别名可关联，既有业务记录不重新编号。
2. 逻辑 `DB_A`、菜单 `DB-A` 和供货 A–G 是调用契约命名。菜单读的是公开版本，供货 D/E 通过权威服务，均未证实连接同一生产物理数据库。身份 Alembic 只用于本地。
3. 中央候选的配送、包装 UUID 与旧演示 `id/code` 展示字段不同。预检适配显式中央业务字段并保留原值；库位字段禁止被猜成某家门店，别名不一致拒绝。中央流转时仍须由 D 依据实际库位与权限校验。
4. SQLite 事实没有统一自动同步，需先解决记录作用域、去重、修正、订单/支付分离和库存来源冲突。绝不把本地收货暂存、模拟支付或座位候选当中央确认。
5. 部署前仍需审计真实 `bsv_stores`、现有员工/学习/库存/审计表和各层有效授权。域注册表未证实任何真实云表名。
