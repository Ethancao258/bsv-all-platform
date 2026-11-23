-- BSV ALL isolated catalog migration 0001.
-- PostgreSQL 17; derived from WorkBuddy V2.2 field/data proposal after review.
-- ISOLATED ONLY: not an official CloudBase migration; do not apply to production.
-- Applied by the versioned isolated migration runner in a single transaction.
-- Does not DROP/TRUNCATE or auto-approve/import sale state.

-- BSV ALL V2.1 候选建表 SQL（仅评审，禁止生产直接执行）
-- 由 build_v21.py 从原Excel快照生成；正式DDL由Codex维护编号迁移。
-- V2.1修复: consumer_count=TEXT; 业务表列与JSONL一一对应; 公式统一入audit.excel_formula_index。
CREATE SCHEMA IF NOT EXISTS catalog;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE catalog.product (
  "sku" TEXT,
  "product_id" TEXT NOT NULL,
  "name_zh" TEXT,
  "sales_series" TEXT,
  "name_en" TEXT,
  "category_l1" TEXT,
  "category_l2" TEXT,
  "category_l3" TEXT,
  "category_l4" TEXT,
  "c_t" TEXT,
  "recipe_text" TEXT,
  "prep_steps_full" TEXT,
  "locator_guide" TEXT,
  "recipe_image_first" TEXT,
  "recipe_image_second" TEXT,
  "final_image_file" TEXT,
  "drink_image_flag" TEXT,
  "method" TEXT,
  "method_intensity" TEXT,
  "prep_duration_sec" INTEGER,
  "glassware" TEXT,
  "product_story" TEXT,
  "flavor_desc" TEXT,
  "flavor_tag" TEXT,
  "abv" NUMERIC(6,2),
  "reference_price_raw" TEXT,
  "prep_note_extra" TEXT,
  "store_op_note" TEXT,
  "portion" NUMERIC(12,3),
  "portion_unit" TEXT,
  "alcohol_attribute" TEXT,
  "allergen" TEXT,
  "image_asset_id" TEXT,
  "recipe_version" TEXT,
  "content_review_status" TEXT,
  "n_input" TEXT,
  "p_input" TEXT,
  "s_input" TEXT,
  "display_flavor_note" TEXT,
  "listing_status" TEXT,
  "image_review_first" TEXT,
  "image_review_second" TEXT,
  ingest_status TEXT NOT NULL DEFAULT 'IMPORTED_RAW',
  _source_sha256 CHAR(64) NOT NULL,
  _excel_row INTEGER NOT NULL,
  _source_sheet CHAR(1),
  PRIMARY KEY ("product_id", _source_sha256),
  UNIQUE (_source_sha256, _excel_row)
);
COMMENT ON TABLE catalog.product IS 'catalog.product；绑定状态=bound';
-- catalog.product 外键候选(经审核后启用): 无
COMMENT ON COLUMN catalog.product."sku" IS 'C列K：SKU';
COMMENT ON COLUMN catalog.product."product_id" IS 'C列L：商品ID';
COMMENT ON COLUMN catalog.product."name_zh" IS 'C列M：商品名称';
COMMENT ON COLUMN catalog.product."sales_series" IS 'C列N：销售系列';
COMMENT ON COLUMN catalog.product."name_en" IS 'C列O：英文名称';
COMMENT ON COLUMN catalog.product."category_l1" IS 'C列P：L1';
COMMENT ON COLUMN catalog.product."category_l2" IS 'C列Q：L2';
COMMENT ON COLUMN catalog.product."category_l3" IS 'C列R：L3';
COMMENT ON COLUMN catalog.product."category_l4" IS 'C列S：L4';
COMMENT ON COLUMN catalog.product."c_t" IS 'C列T：类内编号';
COMMENT ON COLUMN catalog.product."recipe_text" IS 'C列U：配方文字';
COMMENT ON COLUMN catalog.product."prep_steps_full" IS 'C列V：完整制作步骤';
COMMENT ON COLUMN catalog.product."locator_guide" IS 'C列W：寻酒指引';
COMMENT ON COLUMN catalog.product."recipe_image_first" IS 'C列X：配方图文件名｜首次确认';
COMMENT ON COLUMN catalog.product."recipe_image_second" IS 'C列Y：配方图文件名｜二次复核';
COMMENT ON COLUMN catalog.product."final_image_file" IS 'C列Z：成品图文件名';
COMMENT ON COLUMN catalog.product."drink_image_flag" IS 'C列AA：酒图标识';
COMMENT ON COLUMN catalog.product."method" IS 'C列AB：操作方式';
COMMENT ON COLUMN catalog.product."method_intensity" IS 'C列AC：操作力度';
COMMENT ON COLUMN catalog.product."prep_duration_sec" IS 'C列AD：制作时长（秒）';
COMMENT ON COLUMN catalog.product."glassware" IS 'C列AE：杯具';
COMMENT ON COLUMN catalog.product."product_story" IS 'C列AF：产品故事';
COMMENT ON COLUMN catalog.product."flavor_desc" IS 'C列AG：风味描述';
COMMENT ON COLUMN catalog.product."flavor_tag" IS 'C列AH：风味标签';
COMMENT ON COLUMN catalog.product."abv" IS 'C列AI：酒精度数';
COMMENT ON COLUMN catalog.product."reference_price_raw" IS 'C列AJ：标注售价';
COMMENT ON COLUMN catalog.product."prep_note_extra" IS 'C列AK：补充制作说明';
COMMENT ON COLUMN catalog.product."store_op_note" IS 'C列AL：门店操作备注';
COMMENT ON COLUMN catalog.product."portion" IS 'C列AM：份量';
COMMENT ON COLUMN catalog.product."portion_unit" IS 'C列AN：份量单位';
COMMENT ON COLUMN catalog.product."alcohol_attribute" IS 'C列AO：酒精属性';
COMMENT ON COLUMN catalog.product."allergen" IS 'C列AP：过敏原';
COMMENT ON COLUMN catalog.product."image_asset_id" IS 'C列AQ：图片素材ID';
COMMENT ON COLUMN catalog.product."recipe_version" IS 'C列AR：配方版本';
COMMENT ON COLUMN catalog.product."content_review_status" IS 'C列AS：内容审核状态';
COMMENT ON COLUMN catalog.product."n_input" IS 'C列AT：N需求输入';
COMMENT ON COLUMN catalog.product."p_input" IS 'C列AU：P支付输入';
COMMENT ON COLUMN catalog.product."s_input" IS 'C列AV：S场景输入';
COMMENT ON COLUMN catalog.product."display_flavor_note" IS 'C列AW：展示风味说明';
COMMENT ON COLUMN catalog.product."listing_status" IS 'C列AX：上架状态';
COMMENT ON COLUMN catalog.product."image_review_first" IS 'C列AY：首次图审核状态';
COMMENT ON COLUMN catalog.product."image_review_second" IS 'C列AZ：二次图审核状态';
COMMENT ON COLUMN catalog.product."ingest_status" IS '导入层状态，恒IMPORTED_RAW';
COMMENT ON COLUMN catalog.product."_source_sha256" IS '源文件SHA256';
COMMENT ON COLUMN catalog.product."_excel_row" IS 'Excel来源行号(1-based)，非业务ID';
COMMENT ON COLUMN catalog.product."_source_sheet" IS '来源工作表代码 C/P/M/K/R/Q/T';

CREATE TABLE catalog.semifinished (
  "sku" TEXT,
  "semifinished_id" TEXT NOT NULL,
  "name_zh" TEXT,
  "category_l1" TEXT,
  "category_l2" TEXT,
  "category_l3" TEXT,
  "category_l4" TEXT,
  "p_r" TEXT,
  "label_short_code" TEXT,
  "package_qty" NUMERIC(14,3),
  "package_unit" TEXT,
  "shelf_life" TEXT,
  "batch_cost" NUMERIC(14,2),
  "recipe_text" TEXT,
  "prep_steps_full" TEXT,
  "recipe_image_first" TEXT,
  "recipe_image_second" TEXT,
  "final_image_file" TEXT,
  "material_locator" TEXT,
  "storage_condition" TEXT,
  "transport_condition" TEXT,
  "alcohol_attribute" TEXT,
  "sop_version" TEXT,
  "content_review_status" TEXT,
  "label_image_id" TEXT,
  "operation_note" TEXT,
  "method" TEXT,
  "product_story" TEXT,
  "flavor_desc" TEXT,
  "flavor_tag" TEXT,
  "abv" NUMERIC(6,2),
  ingest_status TEXT NOT NULL DEFAULT 'IMPORTED_RAW',
  _source_sha256 CHAR(64) NOT NULL,
  _excel_row INTEGER NOT NULL,
  _source_sheet CHAR(1),
  PRIMARY KEY ("semifinished_id", _source_sha256),
  UNIQUE (_source_sha256, _excel_row)
);
COMMENT ON TABLE catalog.semifinished IS 'catalog.semifinished；绑定状态=bound';
-- catalog.semifinished 外键候选(经审核后启用): 无
COMMENT ON COLUMN catalog.semifinished."sku" IS 'P列K：SKU';
COMMENT ON COLUMN catalog.semifinished."semifinished_id" IS 'P列L：半成品ID';
COMMENT ON COLUMN catalog.semifinished."name_zh" IS 'P列M：半成品名称';
COMMENT ON COLUMN catalog.semifinished."category_l1" IS 'P列N：L1';
COMMENT ON COLUMN catalog.semifinished."category_l2" IS 'P列O：L2';
COMMENT ON COLUMN catalog.semifinished."category_l3" IS 'P列P：L3';
COMMENT ON COLUMN catalog.semifinished."category_l4" IS 'P列Q：L4';
COMMENT ON COLUMN catalog.semifinished."p_r" IS 'P列R：类内编号';
COMMENT ON COLUMN catalog.semifinished."label_short_code" IS 'P列S：标签短码';
COMMENT ON COLUMN catalog.semifinished."package_qty" IS 'P列T：包装量';
COMMENT ON COLUMN catalog.semifinished."package_unit" IS 'P列U：包装单位';
COMMENT ON COLUMN catalog.semifinished."shelf_life" IS 'P列V：保质期';
COMMENT ON COLUMN catalog.semifinished."batch_cost" IS 'P列W：整批成本';
COMMENT ON COLUMN catalog.semifinished."recipe_text" IS 'P列X：配方文字';
COMMENT ON COLUMN catalog.semifinished."prep_steps_full" IS 'P列Y：完整制作步骤';
COMMENT ON COLUMN catalog.semifinished."recipe_image_first" IS 'P列Z：配方图文件名｜首次确认';
COMMENT ON COLUMN catalog.semifinished."recipe_image_second" IS 'P列AA：配方图文件名｜二次复核';
COMMENT ON COLUMN catalog.semifinished."final_image_file" IS 'P列AB：成品图文件名';
COMMENT ON COLUMN catalog.semifinished."material_locator" IS 'P列AC：寻料指引';
COMMENT ON COLUMN catalog.semifinished."storage_condition" IS 'P列AD：储存条件';
COMMENT ON COLUMN catalog.semifinished."transport_condition" IS 'P列AE：运输条件';
COMMENT ON COLUMN catalog.semifinished."alcohol_attribute" IS 'P列AF：酒精属性';
COMMENT ON COLUMN catalog.semifinished."sop_version" IS 'P列AG：SOP版本';
COMMENT ON COLUMN catalog.semifinished."content_review_status" IS 'P列AH：内容审核状态';
COMMENT ON COLUMN catalog.semifinished."label_image_id" IS 'P列AI：标签图形ID';
COMMENT ON COLUMN catalog.semifinished."operation_note" IS 'P列AJ：运营备注';
COMMENT ON COLUMN catalog.semifinished."method" IS 'P列AK：操作方式';
COMMENT ON COLUMN catalog.semifinished."product_story" IS 'P列AL：产品故事';
COMMENT ON COLUMN catalog.semifinished."flavor_desc" IS 'P列AM：风味描述';
COMMENT ON COLUMN catalog.semifinished."flavor_tag" IS 'P列AN：风味标签';
COMMENT ON COLUMN catalog.semifinished."abv" IS 'P列AO：酒精度数';
COMMENT ON COLUMN catalog.semifinished."ingest_status" IS '导入层状态，恒IMPORTED_RAW';
COMMENT ON COLUMN catalog.semifinished."_source_sha256" IS '源文件SHA256';
COMMENT ON COLUMN catalog.semifinished."_excel_row" IS 'Excel来源行号(1-based)，非业务ID';
COMMENT ON COLUMN catalog.semifinished."_source_sheet" IS '来源工作表代码 C/P/M/K/R/Q/T';

CREATE TABLE catalog.material (
  "sku" TEXT,
  "material_id" TEXT NOT NULL,
  "name_zh" TEXT,
  "category_l1" TEXT,
  "category_l2" TEXT,
  "category_l3" TEXT,
  "category_l4" TEXT,
  "m_r" TEXT,
  "identity_role" TEXT,
  "linked_inventory_material_id" TEXT,
  "spec_qty" NUMERIC(14,3),
  "spec_unit" TEXT,
  "original_package_volume" NUMERIC(14,3),
  "sell_deduct_qty" NUMERIC(14,3),
  "is_sellable_raw" TEXT,
  "review_status" TEXT,
  "image_asset_id" TEXT,
  "alias" TEXT,
  "tag" TEXT,
  "purchase_price_raw" TEXT,
  "purchase_channel" TEXT,
  "purchase_url" TEXT,
  "purchase_date_raw" TEXT,
  "depreciation_months" INTEGER,
  "store_id" TEXT,
  "operating_status" TEXT,
  "asset_note" TEXT,
  "operation_note" TEXT,
  "external_entity_id" TEXT,
  ingest_status TEXT NOT NULL DEFAULT 'IMPORTED_RAW',
  _source_sha256 CHAR(64) NOT NULL,
  _excel_row INTEGER NOT NULL,
  _source_sheet CHAR(1),
  PRIMARY KEY ("material_id", _source_sha256),
  UNIQUE (_source_sha256, _excel_row)
);
COMMENT ON TABLE catalog.material IS 'catalog.material；绑定状态=bound';
-- catalog.material 外键候选(经审核后启用): 无
COMMENT ON COLUMN catalog.material."sku" IS 'M列K：SKU';
COMMENT ON COLUMN catalog.material."material_id" IS 'M列L：物料ID';
COMMENT ON COLUMN catalog.material."name_zh" IS 'M列M：物料名称';
COMMENT ON COLUMN catalog.material."category_l1" IS 'M列N：L1';
COMMENT ON COLUMN catalog.material."category_l2" IS 'M列O：L2';
COMMENT ON COLUMN catalog.material."category_l3" IS 'M列P：L3';
COMMENT ON COLUMN catalog.material."category_l4" IS 'M列Q：L4';
COMMENT ON COLUMN catalog.material."m_r" IS 'M列R：类内编号';
COMMENT ON COLUMN catalog.material."identity_role" IS 'M列S：身份角色';
COMMENT ON COLUMN catalog.material."linked_inventory_material_id" IS 'M列T：关联库存物料ID';
COMMENT ON COLUMN catalog.material."spec_qty" IS 'M列U：规格量';
COMMENT ON COLUMN catalog.material."spec_unit" IS 'M列V：规格单位';
COMMENT ON COLUMN catalog.material."original_package_volume" IS 'M列W：原包装容量';
COMMENT ON COLUMN catalog.material."sell_deduct_qty" IS 'M列X：售卖扣减量';
COMMENT ON COLUMN catalog.material."is_sellable_raw" IS 'M列Y：是否可售';
COMMENT ON COLUMN catalog.material."review_status" IS 'M列Z：审核状态';
COMMENT ON COLUMN catalog.material."image_asset_id" IS 'M列AA：图片素材ID';
COMMENT ON COLUMN catalog.material."alias" IS 'M列AB：别名';
COMMENT ON COLUMN catalog.material."tag" IS 'M列AC：标签';
COMMENT ON COLUMN catalog.material."purchase_price_raw" IS 'M列AD：采购价';
COMMENT ON COLUMN catalog.material."purchase_channel" IS 'M列AE：采购渠道';
COMMENT ON COLUMN catalog.material."purchase_url" IS 'M列AF：采购链接';
COMMENT ON COLUMN catalog.material."purchase_date_raw" IS 'M列AG：采购日期';
COMMENT ON COLUMN catalog.material."depreciation_months" IS 'M列AH：折旧月数';
COMMENT ON COLUMN catalog.material."store_id" IS 'M列AI：门店ID';
COMMENT ON COLUMN catalog.material."operating_status" IS 'M列AJ：经营状态';
COMMENT ON COLUMN catalog.material."asset_note" IS 'M列AK：资产备注';
COMMENT ON COLUMN catalog.material."operation_note" IS 'M列AL：运营备注';
COMMENT ON COLUMN catalog.material."external_entity_id" IS 'M列AM：外部主体ID';
COMMENT ON COLUMN catalog.material."ingest_status" IS '导入层状态，恒IMPORTED_RAW';
COMMENT ON COLUMN catalog.material."_source_sha256" IS '源文件SHA256';
COMMENT ON COLUMN catalog.material."_excel_row" IS 'Excel来源行号(1-based)，非业务ID';
COMMENT ON COLUMN catalog.material."_source_sheet" IS '来源工作表代码 C/P/M/K/R/Q/T';

CREATE TABLE catalog.bundle (
  "sku" TEXT,
  "bundle_id" TEXT NOT NULL,
  "name_zh" TEXT,
  "approval_status_raw" TEXT,
  "applicable_channel" TEXT,
  "category_l1" TEXT,
  "category_l2" TEXT,
  "category_l3" TEXT,
  "category_l4" TEXT,
  "k_t" TEXT,
  "bundle_contents" TEXT,
  "full_product_copy" TEXT,
  "store_variant_copy" TEXT,
  "list_price_raw" TEXT,
  "region_reference_price_raw" TEXT,
  "core_reference_price_raw" TEXT,
  "target_budget_range" TEXT,
  "applicable_date_raw" TEXT,
  "design_goal" TEXT,
  "sales_status" TEXT,
  "suggested_persons" INTEGER,
  "demand_task_code" TEXT,
  "demand_task" TEXT,
  "consumer_count" TEXT,
  "payment_budget" TEXT,
  "consumption_scenario" TEXT,
  "substitute_note" TEXT,
  "n_demand_rate" TEXT,
  "p_payment_rate" TEXT,
  "s_scenario_rate" TEXT,
  "nps_result" TEXT,
  "evidence_level" TEXT,
  "nps_evidence" TEXT,
  "data_date_raw" TEXT,
  "sample_denominator" TEXT,
  "model_assumption" TEXT,
  "nps_data_status" TEXT,
  "new_returning" TEXT,
  "weekday_weekend" TEXT,
  "substitute_risk" TEXT,
  "execution_condition" TEXT,
  "evidence_uncertainty" TEXT,
  "business_approval_status" TEXT,
  "next_action" TEXT,
  "recheck_date_raw" TEXT,
  "image_asset_id" TEXT,
  "operation_note" TEXT,
  "bundle_item_link_status" TEXT,
  "demand_category" TEXT,
  "sales_business_zone" TEXT,
  ingest_status TEXT NOT NULL DEFAULT 'IMPORTED_RAW',
  _source_sha256 CHAR(64) NOT NULL,
  _excel_row INTEGER NOT NULL,
  _source_sheet CHAR(1),
  PRIMARY KEY ("bundle_id", _source_sha256),
  UNIQUE (_source_sha256, _excel_row)
);
COMMENT ON TABLE catalog.bundle IS 'catalog.bundle；绑定状态=bound';
-- catalog.bundle 外键候选(经审核后启用): 无
COMMENT ON COLUMN catalog.bundle."sku" IS 'K列K：SKU';
COMMENT ON COLUMN catalog.bundle."bundle_id" IS 'K列L：套餐ID';
COMMENT ON COLUMN catalog.bundle."name_zh" IS 'K列M：套餐名称';
COMMENT ON COLUMN catalog.bundle."approval_status_raw" IS 'K列N：审批状态';
COMMENT ON COLUMN catalog.bundle."applicable_channel" IS 'K列O：适用渠道';
COMMENT ON COLUMN catalog.bundle."category_l1" IS 'K列P：L1';
COMMENT ON COLUMN catalog.bundle."category_l2" IS 'K列Q：L2';
COMMENT ON COLUMN catalog.bundle."category_l3" IS 'K列R：L3';
COMMENT ON COLUMN catalog.bundle."category_l4" IS 'K列S：L4';
COMMENT ON COLUMN catalog.bundle."k_t" IS 'K列T：类内编号';
COMMENT ON COLUMN catalog.bundle."bundle_contents" IS 'K列U：套餐包含内容';
COMMENT ON COLUMN catalog.bundle."full_product_copy" IS 'K列V：完整商品文案';
COMMENT ON COLUMN catalog.bundle."store_variant_copy" IS 'K列W：门店差异文案';
COMMENT ON COLUMN catalog.bundle."list_price_raw" IS 'K列X：标注原价';
COMMENT ON COLUMN catalog.bundle."region_reference_price_raw" IS 'K列Y：区域参考售价';
COMMENT ON COLUMN catalog.bundle."core_reference_price_raw" IS 'K列Z：核心参考售价';
COMMENT ON COLUMN catalog.bundle."target_budget_range" IS 'K列AA：目标预算区间';
COMMENT ON COLUMN catalog.bundle."applicable_date_raw" IS 'K列AB：适用日期';
COMMENT ON COLUMN catalog.bundle."design_goal" IS 'K列AC：设计目标';
COMMENT ON COLUMN catalog.bundle."sales_status" IS 'K列AD：销售状态';
COMMENT ON COLUMN catalog.bundle."suggested_persons" IS 'K列AE：建议人数';
COMMENT ON COLUMN catalog.bundle."demand_task_code" IS 'K列AF：需求任务代码';
COMMENT ON COLUMN catalog.bundle."demand_task" IS 'K列AG：消费需求任务';
COMMENT ON COLUMN catalog.bundle."consumer_count" IS 'K列AH：消费人数';
COMMENT ON COLUMN catalog.bundle."payment_budget" IS 'K列AI：支付预算';
COMMENT ON COLUMN catalog.bundle."consumption_scenario" IS 'K列AJ：消费场景';
COMMENT ON COLUMN catalog.bundle."substitute_note" IS 'K列AK：替代说明';
COMMENT ON COLUMN catalog.bundle."n_demand_rate" IS 'K列AL：N需求率';
COMMENT ON COLUMN catalog.bundle."p_payment_rate" IS 'K列AM：P支付转化率';
COMMENT ON COLUMN catalog.bundle."s_scenario_rate" IS 'K列AN：S场景实现率';
COMMENT ON COLUMN catalog.bundle."nps_result" IS 'K列AO：NPS计算结果';
COMMENT ON COLUMN catalog.bundle."evidence_level" IS 'K列AP：数据证据等级';
COMMENT ON COLUMN catalog.bundle."nps_evidence" IS 'K列AQ：NPS证据依据';
COMMENT ON COLUMN catalog.bundle."data_date_raw" IS 'K列AR：数据日期';
COMMENT ON COLUMN catalog.bundle."sample_denominator" IS 'K列AS：样本与分母';
COMMENT ON COLUMN catalog.bundle."model_assumption" IS 'K列AT：模型假设与局限';
COMMENT ON COLUMN catalog.bundle."nps_data_status" IS 'K列AU：NPS数据状态';
COMMENT ON COLUMN catalog.bundle."new_returning" IS 'K列AV：新老客适用';
COMMENT ON COLUMN catalog.bundle."weekday_weekend" IS 'K列AW：周中周末适用';
COMMENT ON COLUMN catalog.bundle."substitute_risk" IS 'K列AX：替代风险';
COMMENT ON COLUMN catalog.bundle."execution_condition" IS 'K列AY：执行条件';
COMMENT ON COLUMN catalog.bundle."evidence_uncertainty" IS 'K列AZ：证据与不确定性';
COMMENT ON COLUMN catalog.bundle."business_approval_status" IS 'K列BA：业务审批状态';
COMMENT ON COLUMN catalog.bundle."next_action" IS 'K列BB：下一步动作';
COMMENT ON COLUMN catalog.bundle."recheck_date_raw" IS 'K列BC：复检日期';
COMMENT ON COLUMN catalog.bundle."image_asset_id" IS 'K列BD：图片素材ID';
COMMENT ON COLUMN catalog.bundle."operation_note" IS 'K列BE：运营备注';
COMMENT ON COLUMN catalog.bundle."bundle_item_link_status" IS 'K列BF：套餐子项关联状态';
COMMENT ON COLUMN catalog.bundle."demand_category" IS 'K列BG：消费需求分类';
COMMENT ON COLUMN catalog.bundle."sales_business_zone" IS 'K列BH：销售业务分区';
COMMENT ON COLUMN catalog.bundle."ingest_status" IS '导入层状态，恒IMPORTED_RAW';
COMMENT ON COLUMN catalog.bundle."_source_sha256" IS '源文件SHA256';
COMMENT ON COLUMN catalog.bundle."_excel_row" IS 'Excel来源行号(1-based)，非业务ID';
COMMENT ON COLUMN catalog.bundle."_source_sheet" IS '来源工作表代码 C/P/M/K/R/Q/T';

CREATE TABLE catalog.bundle_slot (
  "slot_bundle_id" TEXT,
  "slot_number" INTEGER,
  "slot_name" TEXT,
  "quantity" NUMERIC(12,3),
  "selection_rule" TEXT,
  "candidate_product_id" TEXT,
  "candidate_sku_auto" TEXT,
  "candidate_name_auto" TEXT,
  "link_check" TEXT,
  "fulfillment_constraint" TEXT,
  ingest_status TEXT NOT NULL DEFAULT 'IMPORTED_RAW',
  _source_sha256 CHAR(64) NOT NULL,
  _excel_row INTEGER NOT NULL,
  _source_sheet CHAR(1),
  "slot_row_id" TEXT NOT NULL,
  PRIMARY KEY ("slot_row_id", _source_sha256)
);
COMMENT ON TABLE catalog.bundle_slot IS 'catalog.bundle_slot；绑定状态=placeholder';
-- catalog.bundle_slot 外键候选(经审核后启用): slot_bundle_id -> catalog.bundle.bundle_id
COMMENT ON COLUMN catalog.bundle_slot."slot_bundle_id" IS 'K列CR：套餐ID';
COMMENT ON COLUMN catalog.bundle_slot."slot_number" IS 'K列CS：槽位编号';
COMMENT ON COLUMN catalog.bundle_slot."slot_name" IS 'K列CT：槽位名称';
COMMENT ON COLUMN catalog.bundle_slot."quantity" IS 'K列CU：所需数量';
COMMENT ON COLUMN catalog.bundle_slot."selection_rule" IS 'K列CV：选择规则';
COMMENT ON COLUMN catalog.bundle_slot."candidate_product_id" IS 'K列CW：候选商品ID';
COMMENT ON COLUMN catalog.bundle_slot."candidate_sku_auto" IS 'K列CX：候选商品SKU｜自动';
COMMENT ON COLUMN catalog.bundle_slot."candidate_name_auto" IS 'K列CY：候选商品名称｜自动';
COMMENT ON COLUMN catalog.bundle_slot."link_check" IS 'K列CZ：关联校验';
COMMENT ON COLUMN catalog.bundle_slot."fulfillment_constraint" IS 'K列DA：履约约束说明';
COMMENT ON COLUMN catalog.bundle_slot."ingest_status" IS '导入层状态，恒IMPORTED_RAW';
COMMENT ON COLUMN catalog.bundle_slot."_source_sha256" IS '源文件SHA256';
COMMENT ON COLUMN catalog.bundle_slot."_excel_row" IS 'Excel来源行号(1-based)，非业务ID';
COMMENT ON COLUMN catalog.bundle_slot."_source_sheet" IS '来源工作表代码 C/P/M/K/R/Q/T';
COMMENT ON COLUMN catalog.bundle_slot."slot_row_id" IS '来源行派生键，非业务永久ID';

CREATE TABLE catalog.store_nps (
  "nps_bundle_id" TEXT,
  "store_id" TEXT,
  "nps_n_demand_rate" TEXT,
  "nps_p_payment_rate" TEXT,
  "nps_s_scenario_rate" TEXT,
  "data_marker" TEXT,
  "note" TEXT,
  ingest_status TEXT NOT NULL DEFAULT 'IMPORTED_RAW',
  _source_sha256 CHAR(64) NOT NULL,
  _excel_row INTEGER NOT NULL,
  _source_sheet CHAR(1),
  "nps_row_id" TEXT NOT NULL,
  PRIMARY KEY ("nps_row_id", _source_sha256)
);
COMMENT ON TABLE catalog.store_nps IS 'catalog.store_nps；绑定状态=bound';
-- catalog.store_nps 外键候选(经审核后启用): nps_bundle_id -> catalog.bundle.bundle_id, store_id -> core.store.store_id
COMMENT ON COLUMN catalog.store_nps."nps_bundle_id" IS 'K列DC：套餐ID';
COMMENT ON COLUMN catalog.store_nps."store_id" IS 'K列DD：门店ID';
COMMENT ON COLUMN catalog.store_nps."nps_n_demand_rate" IS 'K列DE：N需求率';
COMMENT ON COLUMN catalog.store_nps."nps_p_payment_rate" IS 'K列DF：P支付转化率';
COMMENT ON COLUMN catalog.store_nps."nps_s_scenario_rate" IS 'K列DG：S场景实现率';
COMMENT ON COLUMN catalog.store_nps."data_marker" IS 'K列DH：数据标记';
COMMENT ON COLUMN catalog.store_nps."note" IS 'K列DI：备注';
COMMENT ON COLUMN catalog.store_nps."ingest_status" IS '导入层状态，恒IMPORTED_RAW';
COMMENT ON COLUMN catalog.store_nps."_source_sha256" IS '源文件SHA256';
COMMENT ON COLUMN catalog.store_nps."_excel_row" IS 'Excel来源行号(1-based)，非业务ID';
COMMENT ON COLUMN catalog.store_nps."_source_sheet" IS '来源工作表代码 C/P/M/K/R/Q/T';
COMMENT ON COLUMN catalog.store_nps."nps_row_id" IS '来源行派生键，非业务永久ID';

CREATE TABLE catalog.recipe_step (
  "sku" TEXT,
  "recipe_step_id" TEXT NOT NULL,
  "record_name" TEXT,
  "category_l1" TEXT,
  "category_l2" TEXT,
  "category_l3" TEXT,
  "category_l4" TEXT,
  "r_r" TEXT,
  "output_link_id" TEXT,
  "output_product_id" TEXT,
  "output_semifinished_id" TEXT,
  "input_material_id" TEXT,
  "input_qty" NUMERIC(12,3),
  "input_unit" TEXT,
  "recipe_text_step" TEXT,
  "prep_steps_full_step" TEXT,
  "locator_guide_step" TEXT,
  "recipe_image_first" TEXT,
  "recipe_image_second" TEXT,
  "prep_duration_sec" INTEGER,
  "method_intensity" TEXT,
  "output_note_extra" TEXT,
  "review_status" TEXT,
  "output_sku_link" TEXT,
  "link_check" TEXT,
  ingest_status TEXT NOT NULL DEFAULT 'IMPORTED_RAW',
  _source_sha256 CHAR(64) NOT NULL,
  _excel_row INTEGER NOT NULL,
  _source_sheet CHAR(1),
  PRIMARY KEY ("recipe_step_id", _source_sha256),
  UNIQUE (_source_sha256, _excel_row)
);
COMMENT ON TABLE catalog.recipe_step IS 'catalog.recipe_step；绑定状态=partial';
-- Isolation migration enforces typed C/P output identity and optional same-revision material reference.
COMMENT ON COLUMN catalog.recipe_step."sku" IS 'R列K：SKU';
COMMENT ON COLUMN catalog.recipe_step."recipe_step_id" IS 'R列L：工序记录ID';
COMMENT ON COLUMN catalog.recipe_step."record_name" IS 'R列M：记录名称';
COMMENT ON COLUMN catalog.recipe_step."category_l1" IS 'R列N：L1';
COMMENT ON COLUMN catalog.recipe_step."category_l2" IS 'R列O：L2';
COMMENT ON COLUMN catalog.recipe_step."category_l3" IS 'R列P：L3';
COMMENT ON COLUMN catalog.recipe_step."category_l4" IS 'R列Q：L4';
COMMENT ON COLUMN catalog.recipe_step."r_r" IS 'R列R：类内编号';
COMMENT ON COLUMN catalog.recipe_step."output_link_id" IS 'R列S：出品关联ID';
COMMENT ON COLUMN catalog.recipe_step."input_material_id" IS 'R列T：投入物料ID';
COMMENT ON COLUMN catalog.recipe_step."input_qty" IS 'R列U：投料数量';
COMMENT ON COLUMN catalog.recipe_step."input_unit" IS 'R列V：投料单位';
COMMENT ON COLUMN catalog.recipe_step."recipe_text_step" IS 'R列W：配方文字｜制作记录';
COMMENT ON COLUMN catalog.recipe_step."prep_steps_full_step" IS 'R列X：完整制作步骤｜制作记录';
COMMENT ON COLUMN catalog.recipe_step."locator_guide_step" IS 'R列Y：寻料指引｜制作记录';
COMMENT ON COLUMN catalog.recipe_step."recipe_image_first" IS 'R列Z：配方图文件名｜首次确认';
COMMENT ON COLUMN catalog.recipe_step."recipe_image_second" IS 'R列AA：配方图文件名｜二次复核';
COMMENT ON COLUMN catalog.recipe_step."prep_duration_sec" IS 'R列AB：制作时长（秒）';
COMMENT ON COLUMN catalog.recipe_step."method_intensity" IS 'R列AC：操作力度';
COMMENT ON COLUMN catalog.recipe_step."output_note_extra" IS 'R列AD：补充出品说明';
COMMENT ON COLUMN catalog.recipe_step."review_status" IS 'R列AE：审核状态';
COMMENT ON COLUMN catalog.recipe_step."output_sku_link" IS 'R列AF：出品SKU｜关联读取';
COMMENT ON COLUMN catalog.recipe_step."link_check" IS 'R列AG：关联校验';
COMMENT ON COLUMN catalog.recipe_step."ingest_status" IS '导入层状态，恒IMPORTED_RAW';
COMMENT ON COLUMN catalog.recipe_step."_source_sha256" IS '源文件SHA256';
COMMENT ON COLUMN catalog.recipe_step."_excel_row" IS 'Excel来源行号(1-based)，非业务ID';
COMMENT ON COLUMN catalog.recipe_step."_source_sheet" IS '来源工作表代码 C/P/M/K/R/Q/T';

CREATE TABLE catalog.price_quote (
  "sku" TEXT,
  "quote_id" TEXT NOT NULL,
  "quote_name" TEXT,
  "category_l1" TEXT,
  "category_l2" TEXT,
  "category_l3" TEXT,
  "category_l4" TEXT,
  "q_r" TEXT,
  "store_id" TEXT,
  "product_id" TEXT,
  "channel" TEXT,
  "pricing_unit" TEXT,
  "approved_price_raw" TEXT,
  "currency" TEXT,
  "review_status" TEXT,
  "valid_from_raw" TEXT,
  "valid_until_raw" TEXT,
  "product_sku_link" TEXT,
  "store_quote_id_auto" TEXT,
  "quote_check" TEXT,
  ingest_status TEXT NOT NULL DEFAULT 'IMPORTED_RAW',
  _source_sha256 CHAR(64) NOT NULL,
  _excel_row INTEGER NOT NULL,
  _source_sheet CHAR(1),
  PRIMARY KEY ("quote_id", _source_sha256),
  UNIQUE (_source_sha256, _excel_row)
);
COMMENT ON TABLE catalog.price_quote IS 'catalog.price_quote；绑定状态=empty_template';
-- catalog.price_quote 外键候选(经审核后启用): store_id -> core.store.store_id, product_id -> catalog.product.product_id
COMMENT ON COLUMN catalog.price_quote."sku" IS 'Q列K：SKU';
COMMENT ON COLUMN catalog.price_quote."quote_id" IS 'Q列L：报价记录ID';
COMMENT ON COLUMN catalog.price_quote."quote_name" IS 'Q列M：报价名称';
COMMENT ON COLUMN catalog.price_quote."category_l1" IS 'Q列N：L1';
COMMENT ON COLUMN catalog.price_quote."category_l2" IS 'Q列O：L2';
COMMENT ON COLUMN catalog.price_quote."category_l3" IS 'Q列P：L3';
COMMENT ON COLUMN catalog.price_quote."category_l4" IS 'Q列Q：L4';
COMMENT ON COLUMN catalog.price_quote."q_r" IS 'Q列R：类内编号';
COMMENT ON COLUMN catalog.price_quote."store_id" IS 'Q列S：门店ID';
COMMENT ON COLUMN catalog.price_quote."product_id" IS 'Q列T：商品ID';
COMMENT ON COLUMN catalog.price_quote."channel" IS 'Q列U：销售渠道';
COMMENT ON COLUMN catalog.price_quote."pricing_unit" IS 'Q列V：计价单位';
COMMENT ON COLUMN catalog.price_quote."approved_price_raw" IS 'Q列W：核准售价';
COMMENT ON COLUMN catalog.price_quote."currency" IS 'Q列X：币种';
COMMENT ON COLUMN catalog.price_quote."review_status" IS 'Q列Y：审核状态';
COMMENT ON COLUMN catalog.price_quote."valid_from_raw" IS 'Q列Z：生效日期';
COMMENT ON COLUMN catalog.price_quote."valid_until_raw" IS 'Q列AA：失效日期';
COMMENT ON COLUMN catalog.price_quote."product_sku_link" IS 'Q列AB：商品SKU｜关联读取';
COMMENT ON COLUMN catalog.price_quote."store_quote_id_auto" IS 'Q列AC：门店报价ID｜自动';
COMMENT ON COLUMN catalog.price_quote."quote_check" IS 'Q列AD：报价校验';
COMMENT ON COLUMN catalog.price_quote."ingest_status" IS '导入层状态，恒IMPORTED_RAW';
COMMENT ON COLUMN catalog.price_quote."_source_sha256" IS '源文件SHA256';
COMMENT ON COLUMN catalog.price_quote."_excel_row" IS 'Excel来源行号(1-based)，非业务ID';
COMMENT ON COLUMN catalog.price_quote."_source_sheet" IS '来源工作表代码 C/P/M/K/R/Q/T';

CREATE TABLE core.store (
  "sku" TEXT,
  "outlet_record_id" TEXT,
  "store_name_zh" TEXT,
  "category_l1" TEXT,
  "category_l2" TEXT,
  "category_l3" TEXT,
  "category_l4" TEXT,
  "t_r" TEXT,
  "store_id" TEXT NOT NULL,
  "business_format" TEXT,
  "operation_mode" TEXT,
  "region" TEXT,
  "currency" TEXT,
  "review_status" TEXT,
  "operation_note" TEXT,
  ingest_status TEXT NOT NULL DEFAULT 'IMPORTED_RAW',
  _source_sha256 CHAR(64) NOT NULL,
  _excel_row INTEGER NOT NULL,
  _source_sheet CHAR(1),
  PRIMARY KEY ("store_id", _source_sha256),
  UNIQUE (_source_sha256, _excel_row)
);
COMMENT ON TABLE core.store IS 'core.store；绑定状态=bound';
-- core.store 外键候选(经审核后启用): 无
COMMENT ON COLUMN core.store."sku" IS 'T列K：SKU';
COMMENT ON COLUMN core.store."outlet_record_id" IS 'T列L：网点记录ID';
COMMENT ON COLUMN core.store."store_name_zh" IS 'T列M：门店名称';
COMMENT ON COLUMN core.store."category_l1" IS 'T列N：L1';
COMMENT ON COLUMN core.store."category_l2" IS 'T列O：L2';
COMMENT ON COLUMN core.store."category_l3" IS 'T列P：L3';
COMMENT ON COLUMN core.store."category_l4" IS 'T列Q：L4';
COMMENT ON COLUMN core.store."t_r" IS 'T列R：类内编号';
COMMENT ON COLUMN core.store."store_id" IS 'T列S：门店ID';
COMMENT ON COLUMN core.store."business_format" IS 'T列T：产品业态';
COMMENT ON COLUMN core.store."operation_mode" IS 'T列U：经营方式';
COMMENT ON COLUMN core.store."region" IS 'T列V：所在区域';
COMMENT ON COLUMN core.store."currency" IS 'T列W：币种';
COMMENT ON COLUMN core.store."review_status" IS 'T列X：审核状态';
COMMENT ON COLUMN core.store."operation_note" IS 'T列Y：运营备注';
COMMENT ON COLUMN core.store."ingest_status" IS '导入层状态，恒IMPORTED_RAW';
COMMENT ON COLUMN core.store."_source_sha256" IS '源文件SHA256';
COMMENT ON COLUMN core.store."_excel_row" IS 'Excel来源行号(1-based)，非业务ID';
COMMENT ON COLUMN core.store."_source_sheet" IS '来源工作表代码 C/P/M/K/R/Q/T';

CREATE TABLE audit.source_dictionary (
  "c_a" TEXT,
  "c_b" TEXT,
  "c_c" TEXT,
  "c_d" TEXT,
  "c_e" TEXT,
  "c_f" TEXT,
  "c_g" TEXT,
  "c_h" TEXT,
  "c_i" TEXT,
  "p_a" TEXT,
  "p_b" TEXT,
  "p_c" TEXT,
  "p_d" TEXT,
  "p_e" TEXT,
  "p_f" TEXT,
  "p_g" TEXT,
  "p_h" TEXT,
  "p_i" TEXT,
  "m_a" TEXT,
  "m_b" TEXT,
  "m_c" TEXT,
  "m_d" TEXT,
  "m_e" TEXT,
  "m_f" TEXT,
  "m_g" TEXT,
  "m_h" TEXT,
  "m_i" TEXT,
  "k_a" TEXT,
  "k_b" TEXT,
  "k_c" TEXT,
  "k_d" TEXT,
  "k_e" TEXT,
  "k_f" TEXT,
  "k_g" TEXT,
  "k_h" TEXT,
  "k_i" TEXT,
  "r_a" TEXT,
  "r_b" TEXT,
  "r_c" TEXT,
  "r_d" TEXT,
  "r_e" TEXT,
  "r_f" TEXT,
  "r_g" TEXT,
  "r_h" TEXT,
  "r_i" TEXT,
  "q_a" TEXT,
  "q_b" TEXT,
  "q_c" TEXT,
  "q_d" TEXT,
  "q_e" TEXT,
  "q_f" TEXT,
  "q_g" TEXT,
  "q_h" TEXT,
  "q_i" TEXT,
  "t_a" TEXT,
  "t_b" TEXT,
  "t_c" TEXT,
  "t_d" TEXT,
  "t_e" TEXT,
  "t_f" TEXT,
  "t_g" TEXT,
  "t_h" TEXT,
  "t_i" TEXT,
  ingest_status TEXT NOT NULL DEFAULT 'IMPORTED_RAW',
  _source_sha256 CHAR(64) NOT NULL,
  _excel_row INTEGER NOT NULL,
  _source_sheet CHAR(1),
  "dict_row_id" TEXT NOT NULL,
  PRIMARY KEY ("dict_row_id", _source_sha256)
);
COMMENT ON TABLE audit.source_dictionary IS 'audit.source_dictionary；绑定状态=n/a';
-- audit.source_dictionary 外键候选(经审核后启用): 无
COMMENT ON COLUMN audit.source_dictionary."c_a" IS '*列C:A：列A';
COMMENT ON COLUMN audit.source_dictionary."c_b" IS '*列C:B：列B';
COMMENT ON COLUMN audit.source_dictionary."c_c" IS '*列C:C：列C';
COMMENT ON COLUMN audit.source_dictionary."c_d" IS '*列C:D：列D';
COMMENT ON COLUMN audit.source_dictionary."c_e" IS '*列C:E：列E';
COMMENT ON COLUMN audit.source_dictionary."c_f" IS '*列C:F：列F';
COMMENT ON COLUMN audit.source_dictionary."c_g" IS '*列C:G：列G';
COMMENT ON COLUMN audit.source_dictionary."c_h" IS '*列C:H：列H';
COMMENT ON COLUMN audit.source_dictionary."c_i" IS '*列C:I：列I';
COMMENT ON COLUMN audit.source_dictionary."p_a" IS '*列P:A：列A';
COMMENT ON COLUMN audit.source_dictionary."p_b" IS '*列P:B：列B';
COMMENT ON COLUMN audit.source_dictionary."p_c" IS '*列P:C：列C';
COMMENT ON COLUMN audit.source_dictionary."p_d" IS '*列P:D：列D';
COMMENT ON COLUMN audit.source_dictionary."p_e" IS '*列P:E：列E';
COMMENT ON COLUMN audit.source_dictionary."p_f" IS '*列P:F：列F';
COMMENT ON COLUMN audit.source_dictionary."p_g" IS '*列P:G：列G';
COMMENT ON COLUMN audit.source_dictionary."p_h" IS '*列P:H：列H';
COMMENT ON COLUMN audit.source_dictionary."p_i" IS '*列P:I：列I';
COMMENT ON COLUMN audit.source_dictionary."m_a" IS '*列M:A：列A';
COMMENT ON COLUMN audit.source_dictionary."m_b" IS '*列M:B：列B';
COMMENT ON COLUMN audit.source_dictionary."m_c" IS '*列M:C：列C';
COMMENT ON COLUMN audit.source_dictionary."m_d" IS '*列M:D：列D';
COMMENT ON COLUMN audit.source_dictionary."m_e" IS '*列M:E：列E';
COMMENT ON COLUMN audit.source_dictionary."m_f" IS '*列M:F：列F';
COMMENT ON COLUMN audit.source_dictionary."m_g" IS '*列M:G：列G';
COMMENT ON COLUMN audit.source_dictionary."m_h" IS '*列M:H：列H';
COMMENT ON COLUMN audit.source_dictionary."m_i" IS '*列M:I：列I';
COMMENT ON COLUMN audit.source_dictionary."k_a" IS '*列K:A：列A';
COMMENT ON COLUMN audit.source_dictionary."k_b" IS '*列K:B：列B';
COMMENT ON COLUMN audit.source_dictionary."k_c" IS '*列K:C：列C';
COMMENT ON COLUMN audit.source_dictionary."k_d" IS '*列K:D：列D';
COMMENT ON COLUMN audit.source_dictionary."k_e" IS '*列K:E：列E';
COMMENT ON COLUMN audit.source_dictionary."k_f" IS '*列K:F：列F';
COMMENT ON COLUMN audit.source_dictionary."k_g" IS '*列K:G：列G';
COMMENT ON COLUMN audit.source_dictionary."k_h" IS '*列K:H：列H';
COMMENT ON COLUMN audit.source_dictionary."k_i" IS '*列K:I：列I';
COMMENT ON COLUMN audit.source_dictionary."r_a" IS '*列R:A：列A';
COMMENT ON COLUMN audit.source_dictionary."r_b" IS '*列R:B：列B';
COMMENT ON COLUMN audit.source_dictionary."r_c" IS '*列R:C：列C';
COMMENT ON COLUMN audit.source_dictionary."r_d" IS '*列R:D：列D';
COMMENT ON COLUMN audit.source_dictionary."r_e" IS '*列R:E：列E';
COMMENT ON COLUMN audit.source_dictionary."r_f" IS '*列R:F：列F';
COMMENT ON COLUMN audit.source_dictionary."r_g" IS '*列R:G：列G';
COMMENT ON COLUMN audit.source_dictionary."r_h" IS '*列R:H：列H';
COMMENT ON COLUMN audit.source_dictionary."r_i" IS '*列R:I：列I';
COMMENT ON COLUMN audit.source_dictionary."q_a" IS '*列Q:A：列A';
COMMENT ON COLUMN audit.source_dictionary."q_b" IS '*列Q:B：列B';
COMMENT ON COLUMN audit.source_dictionary."q_c" IS '*列Q:C：列C';
COMMENT ON COLUMN audit.source_dictionary."q_d" IS '*列Q:D：列D';
COMMENT ON COLUMN audit.source_dictionary."q_e" IS '*列Q:E：列E';
COMMENT ON COLUMN audit.source_dictionary."q_f" IS '*列Q:F：列F';
COMMENT ON COLUMN audit.source_dictionary."q_g" IS '*列Q:G：列G';
COMMENT ON COLUMN audit.source_dictionary."q_h" IS '*列Q:H：列H';
COMMENT ON COLUMN audit.source_dictionary."q_i" IS '*列Q:I：列I';
COMMENT ON COLUMN audit.source_dictionary."t_a" IS '*列T:A：列A';
COMMENT ON COLUMN audit.source_dictionary."t_b" IS '*列T:B：列B';
COMMENT ON COLUMN audit.source_dictionary."t_c" IS '*列T:C：列C';
COMMENT ON COLUMN audit.source_dictionary."t_d" IS '*列T:D：列D';
COMMENT ON COLUMN audit.source_dictionary."t_e" IS '*列T:E：列E';
COMMENT ON COLUMN audit.source_dictionary."t_f" IS '*列T:F：列F';
COMMENT ON COLUMN audit.source_dictionary."t_g" IS '*列T:G：列G';
COMMENT ON COLUMN audit.source_dictionary."t_h" IS '*列T:H：列H';
COMMENT ON COLUMN audit.source_dictionary."t_i" IS '*列T:I：列I';
COMMENT ON COLUMN audit.source_dictionary."ingest_status" IS '导入层状态，恒IMPORTED_RAW';
COMMENT ON COLUMN audit.source_dictionary."_source_sha256" IS '源文件SHA256';
COMMENT ON COLUMN audit.source_dictionary."_excel_row" IS 'Excel来源行号(1-based)，非业务ID';
COMMENT ON COLUMN audit.source_dictionary."_source_sheet" IS '来源工作表代码 C/P/M/K/R/Q/T';
COMMENT ON COLUMN audit.source_dictionary."dict_row_id" IS '来源行派生键，非业务永久ID';

CREATE TABLE audit.source_legal_path (
  "c_ja" TEXT,
  "c_jb" TEXT,
  "c_jc" TEXT,
  "c_jd" TEXT,
  "c_je" TEXT,
  "c_jf" TEXT,
  "p_ja" TEXT,
  "p_jb" TEXT,
  "p_jc" TEXT,
  "p_jd" TEXT,
  "p_je" TEXT,
  "p_jf" TEXT,
  "m_ja" TEXT,
  "m_jb" TEXT,
  "m_jc" TEXT,
  "m_jd" TEXT,
  "m_je" TEXT,
  "m_jf" TEXT,
  "k_ja" TEXT,
  "k_jb" TEXT,
  "k_jc" TEXT,
  "k_jd" TEXT,
  "k_je" TEXT,
  "k_jf" TEXT,
  "r_ja" TEXT,
  "r_jb" TEXT,
  "r_jc" TEXT,
  "r_jd" TEXT,
  "r_je" TEXT,
  "r_jf" TEXT,
  "q_ja" TEXT,
  "q_jb" TEXT,
  "q_jc" TEXT,
  "q_jd" TEXT,
  "q_je" TEXT,
  "q_jf" TEXT,
  "t_ja" TEXT,
  "t_jb" TEXT,
  "t_jc" TEXT,
  "t_jd" TEXT,
  "t_je" TEXT,
  "t_jf" TEXT,
  ingest_status TEXT NOT NULL DEFAULT 'IMPORTED_RAW',
  _source_sha256 CHAR(64) NOT NULL,
  _excel_row INTEGER NOT NULL,
  _source_sheet CHAR(1),
  "legal_row_id" TEXT NOT NULL,
  PRIMARY KEY ("legal_row_id", _source_sha256)
);
COMMENT ON TABLE audit.source_legal_path IS 'audit.source_legal_path；绑定状态=n/a';
-- audit.source_legal_path 外键候选(经审核后启用): 无
COMMENT ON COLUMN audit.source_legal_path."c_ja" IS '*列C:JA：L1字典序位';
COMMENT ON COLUMN audit.source_legal_path."c_jb" IS '*列C:JB：L2字典序位';
COMMENT ON COLUMN audit.source_legal_path."c_jc" IS '*列C:JC：L3字典序位';
COMMENT ON COLUMN audit.source_legal_path."c_jd" IS '*列C:JD：L4字典序位';
COMMENT ON COLUMN audit.source_legal_path."c_je" IS '*列C:JE：合法分类码｜计算';
COMMENT ON COLUMN audit.source_legal_path."c_jf" IS '*列C:JF：路径校验';
COMMENT ON COLUMN audit.source_legal_path."p_ja" IS '*列P:JA：L1字典序位';
COMMENT ON COLUMN audit.source_legal_path."p_jb" IS '*列P:JB：L2字典序位';
COMMENT ON COLUMN audit.source_legal_path."p_jc" IS '*列P:JC：L3字典序位';
COMMENT ON COLUMN audit.source_legal_path."p_jd" IS '*列P:JD：L4字典序位';
COMMENT ON COLUMN audit.source_legal_path."p_je" IS '*列P:JE：合法分类码｜计算';
COMMENT ON COLUMN audit.source_legal_path."p_jf" IS '*列P:JF：路径校验';
COMMENT ON COLUMN audit.source_legal_path."m_ja" IS '*列M:JA：L1字典序位';
COMMENT ON COLUMN audit.source_legal_path."m_jb" IS '*列M:JB：L2字典序位';
COMMENT ON COLUMN audit.source_legal_path."m_jc" IS '*列M:JC：L3字典序位';
COMMENT ON COLUMN audit.source_legal_path."m_jd" IS '*列M:JD：L4字典序位';
COMMENT ON COLUMN audit.source_legal_path."m_je" IS '*列M:JE：合法分类码｜计算';
COMMENT ON COLUMN audit.source_legal_path."m_jf" IS '*列M:JF：路径校验';
COMMENT ON COLUMN audit.source_legal_path."k_ja" IS '*列K:JA：L1字典序位';
COMMENT ON COLUMN audit.source_legal_path."k_jb" IS '*列K:JB：L2字典序位';
COMMENT ON COLUMN audit.source_legal_path."k_jc" IS '*列K:JC：L3字典序位';
COMMENT ON COLUMN audit.source_legal_path."k_jd" IS '*列K:JD：L4字典序位';
COMMENT ON COLUMN audit.source_legal_path."k_je" IS '*列K:JE：合法分类码｜计算';
COMMENT ON COLUMN audit.source_legal_path."k_jf" IS '*列K:JF：路径校验';
COMMENT ON COLUMN audit.source_legal_path."r_ja" IS '*列R:JA：L1字典序位';
COMMENT ON COLUMN audit.source_legal_path."r_jb" IS '*列R:JB：L2字典序位';
COMMENT ON COLUMN audit.source_legal_path."r_jc" IS '*列R:JC：L3字典序位';
COMMENT ON COLUMN audit.source_legal_path."r_jd" IS '*列R:JD：L4字典序位';
COMMENT ON COLUMN audit.source_legal_path."r_je" IS '*列R:JE：合法分类码｜计算';
COMMENT ON COLUMN audit.source_legal_path."r_jf" IS '*列R:JF：路径校验';
COMMENT ON COLUMN audit.source_legal_path."q_ja" IS '*列Q:JA：L1字典序位';
COMMENT ON COLUMN audit.source_legal_path."q_jb" IS '*列Q:JB：L2字典序位';
COMMENT ON COLUMN audit.source_legal_path."q_jc" IS '*列Q:JC：L3字典序位';
COMMENT ON COLUMN audit.source_legal_path."q_jd" IS '*列Q:JD：L4字典序位';
COMMENT ON COLUMN audit.source_legal_path."q_je" IS '*列Q:JE：合法分类码｜计算';
COMMENT ON COLUMN audit.source_legal_path."q_jf" IS '*列Q:JF：路径校验';
COMMENT ON COLUMN audit.source_legal_path."t_ja" IS '*列T:JA：L1字典序位';
COMMENT ON COLUMN audit.source_legal_path."t_jb" IS '*列T:JB：L2字典序位';
COMMENT ON COLUMN audit.source_legal_path."t_jc" IS '*列T:JC：L3字典序位';
COMMENT ON COLUMN audit.source_legal_path."t_jd" IS '*列T:JD：L4字典序位';
COMMENT ON COLUMN audit.source_legal_path."t_je" IS '*列T:JE：合法分类码｜计算';
COMMENT ON COLUMN audit.source_legal_path."t_jf" IS '*列T:JF：路径校验';
COMMENT ON COLUMN audit.source_legal_path."ingest_status" IS '导入层状态，恒IMPORTED_RAW';
COMMENT ON COLUMN audit.source_legal_path."_source_sha256" IS '源文件SHA256';
COMMENT ON COLUMN audit.source_legal_path."_excel_row" IS 'Excel来源行号(1-based)，非业务ID';
COMMENT ON COLUMN audit.source_legal_path."_source_sheet" IS '来源工作表代码 C/P/M/K/R/Q/T';
COMMENT ON COLUMN audit.source_legal_path."legal_row_id" IS '来源行派生键，非业务永久ID';

CREATE TABLE audit.source_calc (
  "c_ea" TEXT,
  "c_eb" TEXT,
  "c_ec" TEXT,
  "c_ed" TEXT,
  "c_ee" TEXT,
  "c_ef" TEXT,
  "c_eg" TEXT,
  "p_ea" TEXT,
  "p_eb" TEXT,
  "p_ec" TEXT,
  "p_ed" TEXT,
  "p_ee" TEXT,
  "p_ef" TEXT,
  "p_eg" TEXT,
  "m_ea" TEXT,
  "m_eb" TEXT,
  "m_ec" TEXT,
  "m_ed" TEXT,
  "m_ee" TEXT,
  "m_ef" TEXT,
  "m_eg" TEXT,
  "k_ea" TEXT,
  "k_eb" TEXT,
  "k_ec" TEXT,
  "k_ed" TEXT,
  "k_ee" TEXT,
  "k_ef" TEXT,
  "k_eg" TEXT,
  "r_ea" TEXT,
  "r_eb" TEXT,
  "r_ec" TEXT,
  "r_ed" TEXT,
  "r_ee" TEXT,
  "r_ef" TEXT,
  "r_eg" TEXT,
  "q_ea" TEXT,
  "q_eb" TEXT,
  "q_ec" TEXT,
  "q_ed" TEXT,
  "q_ee" TEXT,
  "q_ef" TEXT,
  "q_eg" TEXT,
  "t_ea" TEXT,
  "t_eb" TEXT,
  "t_ec" TEXT,
  "t_ed" TEXT,
  "t_ee" TEXT,
  "t_ef" TEXT,
  "t_eg" TEXT,
  ingest_status TEXT NOT NULL DEFAULT 'IMPORTED_RAW',
  _source_sha256 CHAR(64) NOT NULL,
  _excel_row INTEGER NOT NULL,
  _source_sheet CHAR(1),
  "calc_row_id" TEXT NOT NULL,
  PRIMARY KEY ("calc_row_id", _source_sha256)
);
COMMENT ON TABLE audit.source_calc IS 'audit.source_calc；绑定状态=n/a';
-- audit.source_calc 外键候选(经审核后启用): 无
COMMENT ON COLUMN audit.source_calc."c_ea" IS '*列C:EA：L1代码｜计算';
COMMENT ON COLUMN audit.source_calc."c_eb" IS '*列C:EB：L2代码｜计算';
COMMENT ON COLUMN audit.source_calc."c_ec" IS '*列C:EC：L3代码｜计算';
COMMENT ON COLUMN audit.source_calc."c_ed" IS '*列C:ED：L4代码｜计算';
COMMENT ON COLUMN audit.source_calc."c_ee" IS '*列C:EE：分类合法性｜计算';
COMMENT ON COLUMN audit.source_calc."c_ef" IS '*列C:EF：SKU唯一性｜计算';
COMMENT ON COLUMN audit.source_calc."c_eg" IS '*列C:EG：结构入库判定｜计算';
COMMENT ON COLUMN audit.source_calc."p_ea" IS '*列P:EA：L1代码｜计算';
COMMENT ON COLUMN audit.source_calc."p_eb" IS '*列P:EB：L2代码｜计算';
COMMENT ON COLUMN audit.source_calc."p_ec" IS '*列P:EC：L3代码｜计算';
COMMENT ON COLUMN audit.source_calc."p_ed" IS '*列P:ED：L4代码｜计算';
COMMENT ON COLUMN audit.source_calc."p_ee" IS '*列P:EE：分类合法性｜计算';
COMMENT ON COLUMN audit.source_calc."p_ef" IS '*列P:EF：SKU唯一性｜计算';
COMMENT ON COLUMN audit.source_calc."p_eg" IS '*列P:EG：结构入库判定｜计算';
COMMENT ON COLUMN audit.source_calc."m_ea" IS '*列M:EA：L1代码｜计算';
COMMENT ON COLUMN audit.source_calc."m_eb" IS '*列M:EB：L2代码｜计算';
COMMENT ON COLUMN audit.source_calc."m_ec" IS '*列M:EC：L3代码｜计算';
COMMENT ON COLUMN audit.source_calc."m_ed" IS '*列M:ED：L4代码｜计算';
COMMENT ON COLUMN audit.source_calc."m_ee" IS '*列M:EE：分类合法性｜计算';
COMMENT ON COLUMN audit.source_calc."m_ef" IS '*列M:EF：SKU唯一性｜计算';
COMMENT ON COLUMN audit.source_calc."m_eg" IS '*列M:EG：结构入库判定｜计算';
COMMENT ON COLUMN audit.source_calc."k_ea" IS '*列K:EA：L1代码｜计算';
COMMENT ON COLUMN audit.source_calc."k_eb" IS '*列K:EB：L2代码｜计算';
COMMENT ON COLUMN audit.source_calc."k_ec" IS '*列K:EC：L3代码｜计算';
COMMENT ON COLUMN audit.source_calc."k_ed" IS '*列K:ED：L4代码｜计算';
COMMENT ON COLUMN audit.source_calc."k_ee" IS '*列K:EE：分类合法性｜计算';
COMMENT ON COLUMN audit.source_calc."k_ef" IS '*列K:EF：SKU唯一性｜计算';
COMMENT ON COLUMN audit.source_calc."k_eg" IS '*列K:EG：结构入库判定｜计算';
COMMENT ON COLUMN audit.source_calc."r_ea" IS '*列R:EA：L1代码｜计算';
COMMENT ON COLUMN audit.source_calc."r_eb" IS '*列R:EB：L2代码｜计算';
COMMENT ON COLUMN audit.source_calc."r_ec" IS '*列R:EC：L3代码｜计算';
COMMENT ON COLUMN audit.source_calc."r_ed" IS '*列R:ED：L4代码｜计算';
COMMENT ON COLUMN audit.source_calc."r_ee" IS '*列R:EE：分类合法性｜计算';
COMMENT ON COLUMN audit.source_calc."r_ef" IS '*列R:EF：SKU唯一性｜计算';
COMMENT ON COLUMN audit.source_calc."r_eg" IS '*列R:EG：结构入库判定｜计算';
COMMENT ON COLUMN audit.source_calc."q_ea" IS '*列Q:EA：L1代码｜计算';
COMMENT ON COLUMN audit.source_calc."q_eb" IS '*列Q:EB：L2代码｜计算';
COMMENT ON COLUMN audit.source_calc."q_ec" IS '*列Q:EC：L3代码｜计算';
COMMENT ON COLUMN audit.source_calc."q_ed" IS '*列Q:ED：L4代码｜计算';
COMMENT ON COLUMN audit.source_calc."q_ee" IS '*列Q:EE：分类合法性｜计算';
COMMENT ON COLUMN audit.source_calc."q_ef" IS '*列Q:EF：SKU唯一性｜计算';
COMMENT ON COLUMN audit.source_calc."q_eg" IS '*列Q:EG：结构入库判定｜计算';
COMMENT ON COLUMN audit.source_calc."t_ea" IS '*列T:EA：L1代码｜计算';
COMMENT ON COLUMN audit.source_calc."t_eb" IS '*列T:EB：L2代码｜计算';
COMMENT ON COLUMN audit.source_calc."t_ec" IS '*列T:EC：L3代码｜计算';
COMMENT ON COLUMN audit.source_calc."t_ed" IS '*列T:ED：L4代码｜计算';
COMMENT ON COLUMN audit.source_calc."t_ee" IS '*列T:EE：分类合法性｜计算';
COMMENT ON COLUMN audit.source_calc."t_ef" IS '*列T:EF：SKU唯一性｜计算';
COMMENT ON COLUMN audit.source_calc."t_eg" IS '*列T:EG：结构入库判定｜计算';
COMMENT ON COLUMN audit.source_calc."ingest_status" IS '导入层状态，恒IMPORTED_RAW';
COMMENT ON COLUMN audit.source_calc."_source_sha256" IS '源文件SHA256';
COMMENT ON COLUMN audit.source_calc."_excel_row" IS 'Excel来源行号(1-based)，非业务ID';
COMMENT ON COLUMN audit.source_calc."_source_sheet" IS '来源工作表代码 C/P/M/K/R/Q/T';
COMMENT ON COLUMN audit.source_calc."calc_row_id" IS '来源行派生键，非业务永久ID';

CREATE TABLE audit.excel_formula_index (
  formula_id BIGSERIAL PRIMARY KEY,
  source_sha256 CHAR(64) NOT NULL, sheet_code CHAR(1) NOT NULL, cell_address TEXT NOT NULL,
  col_letter TEXT, row_num INTEGER, source_region TEXT, header_zh TEXT,
  formula_text TEXT NOT NULL, is_array BOOLEAN, array_ref TEXT,
  cached_value TEXT, cached_type TEXT,
  UNIQUE (source_sha256, sheet_code, cell_address)
);
-- 公式原文与缓存分离保存；业务表仅存有效值，禁止以公式文本冒充已计算的SKU。


-- Import controls are isolated-catalog metadata. These records never approve sale.
CREATE TABLE audit.import_batch (
  batch_id UUID PRIMARY KEY,
  source_sha256 CHAR(64) NOT NULL UNIQUE,
  package_sha256 CHAR(64) NOT NULL,
  package_version TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('COMMITTED_RAW')),
  counts JSONB NOT NULL,
  imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
  CHECK (package_sha256 ~ '^[0-9a-f]{64}$')
);
CREATE TABLE catalog.active_content (
  singleton_id SMALLINT PRIMARY KEY CHECK (singleton_id = 1),
  source_sha256 CHAR(64) NOT NULL REFERENCES audit.import_batch(source_sha256),
  content_revision BIGINT NOT NULL CHECK (content_revision > 0),
  activated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  activation_status TEXT NOT NULL DEFAULT 'IMPORTED_RAW' CHECK (activation_status = 'IMPORTED_RAW')
);
CREATE TABLE audit.source_mapping (
  source_sha256 CHAR(64) NOT NULL,
  mapping_row INTEGER NOT NULL CHECK (mapping_row > 0),
  excel_address TEXT NOT NULL,
  excel_col TEXT,
  excel_header_zh TEXT,
  excel_region TEXT,
  target_table TEXT NOT NULL,
  target_column TEXT NOT NULL,
  transform TEXT,
  reversibility TEXT,
  PRIMARY KEY (source_sha256, mapping_row),
  FOREIGN KEY (source_sha256) REFERENCES audit.import_batch(source_sha256)
);
CREATE TABLE audit.field_dictionary (
  source_sha256 CHAR(64) NOT NULL,
  dictionary_row INTEGER NOT NULL CHECK (dictionary_row > 0),
  semantic_key TEXT NOT NULL,
  target_table TEXT NOT NULL,
  column_name TEXT NOT NULL,
  source_sheet TEXT NOT NULL,
  source_col TEXT NOT NULL,
  source_header_zh TEXT,
  data_type TEXT NOT NULL,
  key_role TEXT,
  permission_class TEXT NOT NULL CHECK (permission_class IN ('PUBLIC','INTERNAL','CONFIDENTIAL','RESTRICTED')),
  null_meaning TEXT,
  id_note TEXT,
  PRIMARY KEY (source_sha256, dictionary_row),
  UNIQUE (source_sha256, semantic_key),
  FOREIGN KEY (source_sha256) REFERENCES audit.import_batch(source_sha256)
);
CREATE TABLE audit.source_record (
  source_sha256 CHAR(64) NOT NULL,
  entity_table TEXT NOT NULL,
  record_id TEXT NOT NULL,
  excel_row INTEGER NOT NULL,
  raw_fields JSONB NOT NULL,
  PRIMARY KEY (source_sha256, entity_table, record_id),
  FOREIGN KEY (source_sha256) REFERENCES audit.import_batch(source_sha256)
);

-- Relationships are constrained only where the source supplies stable IDs.
ALTER TABLE catalog.bundle_slot ADD CONSTRAINT fk_bundle_slot_bundle_revision
  FOREIGN KEY (slot_bundle_id, _source_sha256) REFERENCES catalog.bundle(bundle_id, _source_sha256);
ALTER TABLE catalog.store_nps ADD CONSTRAINT fk_store_nps_bundle_revision
  FOREIGN KEY (nps_bundle_id, _source_sha256) REFERENCES catalog.bundle(bundle_id, _source_sha256);
ALTER TABLE catalog.store_nps ADD CONSTRAINT fk_store_nps_store_revision
  FOREIGN KEY (store_id, _source_sha256) REFERENCES core.store(store_id, _source_sha256);
ALTER TABLE catalog.recipe_step ADD CONSTRAINT fk_recipe_output_product_revision
  FOREIGN KEY (output_product_id, _source_sha256) REFERENCES catalog.product(product_id, _source_sha256);
ALTER TABLE catalog.recipe_step ADD CONSTRAINT fk_recipe_output_semifinished_revision
  FOREIGN KEY (output_semifinished_id, _source_sha256) REFERENCES catalog.semifinished(semifinished_id, _source_sha256);
ALTER TABLE catalog.recipe_step ADD CONSTRAINT fk_recipe_input_material_revision
  FOREIGN KEY (input_material_id, _source_sha256) REFERENCES catalog.material(material_id, _source_sha256);
ALTER TABLE catalog.recipe_step ADD CONSTRAINT ck_recipe_output_typed
  CHECK ((output_link_id IS NULL AND output_product_id IS NULL AND output_semifinished_id IS NULL)
    OR (output_link_id LIKE 'C%' AND output_product_id = output_link_id AND output_semifinished_id IS NULL)
    OR (output_link_id LIKE 'P%' AND output_semifinished_id = output_link_id AND output_product_id IS NULL));
ALTER TABLE audit.excel_formula_index ADD CONSTRAINT fk_formula_import_revision
  FOREIGN KEY (source_sha256) REFERENCES audit.import_batch(source_sha256);

-- The runtime connects as an externally managed role and must explicitly SET ROLE
-- to this non-login read-only principal. Membership is configured by the isolated
-- deployment operator; no credentials or login role are created by this migration.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='bsv_catalog_reader'
             AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole)) THEN
    RAISE EXCEPTION 'existing bsv_catalog_reader role is not a restricted non-login role';
  ELSIF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='bsv_catalog_reader') THEN
    CREATE ROLE bsv_catalog_reader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
  END IF;
END $$;
GRANT USAGE ON SCHEMA catalog, core, audit TO bsv_catalog_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA catalog, core, audit TO bsv_catalog_reader;
