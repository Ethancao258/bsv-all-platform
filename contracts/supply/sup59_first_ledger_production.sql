-- SUP59 first authoritative inventory ledger. Reviewed deployment candidate only.
-- Run ONLY after C and D establish that no other authoritative D or event ledger exists,
-- approve this exact SQL and target, back up and rehearse restore. Never run at startup.
-- C prepares NOLOGIN bsv_supply_owner and restricted LOGIN bsv_supply_runtime.
-- The migration executor must SET ROLE bsv_supply_owner and set an actual approval reference.
-- No user, inventory, credential, catalog, or demo data is imported.
BEGIN;
SELECT pg_advisory_xact_lock(hashtextextended('BSV:SUP59:FIRST_LEDGER',0));
DO $guard$
BEGIN
 IF current_database()<>'bsv_all_prod' OR current_user<>'bsv_supply_owner'
    OR nullif(current_setting('bsv.sup59_approval_ref',true),'') IS NULL
 THEN RAISE EXCEPTION 'approved sole D owner and bsv_all_prod required'; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND NOT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolbypassrls)
 OR NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='bsv_supply_runtime' AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls)
 OR EXISTS(SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname='bsv_supply_runtime'))
 THEN RAISE EXCEPTION 'dedicated minimally privileged supply roles required'; END IF;
 IF to_regnamespace('catalog') IS NULL OR to_regnamespace('core') IS NULL OR to_regnamespace('audit') IS NULL
 OR to_regclass('catalog.active_content') IS NULL OR to_regclass('catalog.semifinished') IS NULL
 OR to_regnamespace('supply') IS NOT NULL OR to_regnamespace('event_audit') IS NOT NULL
 THEN RAISE EXCEPTION 'existing catalog required; existing D/audit requires owner mapping, never duplicate'; END IF;
END $guard$;
-- BSV ALL｜中央 PostgreSQL schema 设计提案，禁止直接运行生产环境。
-- 表名全部为逻辑提案；必须先与现有公司库核对，复用主表及主键。
-- 不创建产品、门店、人事副本。实际 FK 请引用主库已批准的正式表。
CREATE SCHEMA IF NOT EXISTS supply;
CREATE TABLE IF NOT EXISTS supply.shipment (
  shipment_id uuid PRIMARY KEY,
  source_location_id text NOT NULL,
  dest_location_id text NOT NULL,
  state text NOT NULL CHECK(state IN ('DRAFT','READY','DISPATCHED','PARTIAL_RECEIVED','RECEIVED','DISPUTED','CLOSED','CANCELLED')),
  version integer NOT NULL DEFAULT 1 CHECK(version>=1),
  created_by_employee_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (source_location_id<>dest_location_id)
);
CREATE TABLE IF NOT EXISTS supply.shipment_package (
  package_id uuid PRIMARY KEY,
  shipment_id uuid NOT NULL REFERENCES supply.shipment(shipment_id),
  item_id text NOT NULL, -- FK 到公司产品主数据；此处不复制主表
  lot_id text NOT NULL,  -- 参考公司批次身份；接入审核后加 FK
  base_uom text NOT NULL,
  qty_base numeric(18,4) NOT NULL CHECK(qty_base>0),
  state text NOT NULL CHECK(state IN ('DRAFT','READY','IN_TRANSIT','ACCEPTED','HOLD','RETURNED','SCRAPPED'))
);
CREATE INDEX IF NOT EXISTS idx_bsv_supply_package_shipment ON supply.shipment_package(shipment_id);
CREATE TABLE IF NOT EXISTS supply.movement (
  movement_id uuid PRIMARY KEY,
  request_id uuid NOT NULL,
  shipment_id uuid REFERENCES supply.shipment(shipment_id),
  package_id uuid REFERENCES supply.shipment_package(package_id),
  item_id text NOT NULL,
  lot_id text NOT NULL,
  from_location_id text NOT NULL,
  to_location_id text NOT NULL,
  qty_base numeric(18,4) NOT NULL CHECK(qty_base>0),
  actor_employee_id text NOT NULL,
  occurred_at timestamptz,
  committed_at timestamptz NOT NULL DEFAULT now(),
  CHECK(from_location_id<>to_location_id)
);
CREATE INDEX IF NOT EXISTS idx_bsv_supply_movement_from ON supply.movement(from_location_id,item_id,lot_id);
CREATE INDEX IF NOT EXISTS idx_bsv_supply_movement_to ON supply.movement(to_location_id,item_id,lot_id);
CREATE TABLE IF NOT EXISTS supply.idempotent_result (
  actor_scope text NOT NULL,
  request_id uuid NOT NULL,
  fingerprint text NOT NULL,
  response jsonb NOT NULL,
  committed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(actor_scope,request_id)
);
CREATE TABLE IF NOT EXISTS supply.stock_count (
  count_id uuid PRIMARY KEY,
  location_id text NOT NULL,
  item_id text NOT NULL,
  observer_employee_id text NOT NULL,
  full_package_count integer NOT NULL CHECK(full_package_count>=0),
  opened_count integer NOT NULL CHECK(opened_count>=0),
  opened_bucket_pct integer CHECK(opened_bucket_pct IN (0,25,50,75,100)),
  method text NOT NULL CHECK(method IN ('FIVE_BUCKET','UNKNOWN','EXACT_MEASUREMENT')),
  observed_at timestamptz NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT now(),
  -- 不存在直接触发正式库存结转的触发器；盘点只是观测。
  CHECK (NOT (method='FIVE_BUCKET' AND opened_count>1))
);
-- 公司若已有 outbox/audit，必须复用，不能按此提案再造。
-- 生产 ledger 的函数须：BEGIN -> 幂等键/包装状态/权限验证 -> SELECT FOR UPDATE 库存来源
-- -> 同事务 movement/余额投影/outbox 提交 -> 返回版本。禁止负库存、重复结算。

ALTER TABLE supply.shipment ADD COLUMN central_legal text,
 ADD COLUMN eta timestamptz, ADD COLUMN sent_at timestamptz,
 ADD COLUMN sender_id text, ADD COLUMN arrived_at timestamptz, ADD COLUMN dispatched jsonb;
ALTER TABLE supply.shipment_package ALTER COLUMN shipment_id DROP NOT NULL,
 ADD COLUMN central_legal text, ADD COLUMN stock_location_id text,
 ADD COLUMN remaining_base numeric(18,4), ADD COLUMN version integer,
 ADD COLUMN opened_at timestamptz, ADD COLUMN expires_at timestamptz,
 ADD COLUMN original jsonb, ADD COLUMN opening_evidence_id text, ADD COLUMN recall_reason text, ADD COLUMN recalled_at timestamptz,
 ADD CONSTRAINT sup59_package_facts CHECK (central_legal IS NULL OR
 (stock_location_id IS NOT NULL AND remaining_base IS NOT NULL AND remaining_base>=0
 AND remaining_base<=qty_base AND version IS NOT NULL AND version>=1 AND expires_at IS NOT NULL AND original IS NOT NULL));
CREATE UNIQUE INDEX sup59_opening_once ON supply.shipment_package(central_legal,opening_evidence_id) WHERE opening_evidence_id IS NOT NULL;
CREATE INDEX sup59_stock_location ON supply.shipment_package(central_legal,stock_location_id,item_id);
ALTER TABLE supply.movement ADD COLUMN central_kind text;
CREATE TABLE supply.central_plan (
 plan_id uuid PRIMARY KEY, legal_entity_id text NOT NULL, source_location_id text NOT NULL,
 dest_location_id text NOT NULL, item_id text NOT NULL, facts jsonb NOT NULL,
 created_at timestamptz NOT NULL, CHECK(source_location_id<>dest_location_id));
CREATE TABLE supply.central_batch (
 batch_id uuid PRIMARY KEY, plan_id uuid UNIQUE REFERENCES supply.central_plan(plan_id),
 legal_entity_id text NOT NULL, facts jsonb NOT NULL);
CREATE TABLE supply.central_receipt (
 shipment_id uuid NOT NULL REFERENCES supply.shipment(shipment_id),
 package_id uuid NOT NULL REFERENCES supply.shipment_package(package_id),
 facts jsonb NOT NULL, PRIMARY KEY(shipment_id,package_id));
CREATE TABLE supply.central_print (
 request_id uuid NOT NULL, package_id uuid NOT NULL REFERENCES supply.shipment_package(package_id),
 operation text NOT NULL CHECK(operation IN ('PRINT','REPRINT','CONFIRM')),
 original_request_id uuid, actor_id text NOT NULL, occurred_at timestamptz NOT NULL,
 PRIMARY KEY(request_id,package_id));
CREATE UNIQUE INDEX sup59_print_confirm_once ON supply.central_print(package_id,original_request_id)
 WHERE operation='CONFIRM';
-- Existing D legacy writers MUST reject these central rows or call the same
-- transaction implementation. Do not grant application users direct SQL writes.

-- Accidental legacy-path protection; not a privilege boundary against a DB owner.
-- Real D service roles must still prohibit direct writes by external callers.
CREATE FUNCTION supply.sup59_guard_object() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owned boolean := false;
BEGIN
 IF TG_OP <> 'INSERT' THEN owned := OLD.central_legal IS NOT NULL; END IF;
 IF TG_OP <> 'DELETE' THEN owned := owned OR NEW.central_legal IS NOT NULL; END IF;
 IF owned AND current_setting('bsv.sup59_command',true) IS DISTINCT FROM '1' THEN
   RAISE EXCEPTION 'SUP59 managed row: use the D command API' USING ERRCODE='23514';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END $$;
CREATE TRIGGER sup59_shipment_guard BEFORE INSERT OR UPDATE OR DELETE ON supply.shipment
 FOR EACH ROW EXECUTE FUNCTION supply.sup59_guard_object();
CREATE TRIGGER sup59_package_guard BEFORE INSERT OR UPDATE OR DELETE ON supply.shipment_package
 FOR EACH ROW EXECUTE FUNCTION supply.sup59_guard_object();
CREATE FUNCTION supply.sup59_guard_movement() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owned boolean := false;
BEGIN
 IF TG_OP <> 'INSERT' THEN
   owned := OLD.central_kind IS NOT NULL OR EXISTS(SELECT 1 FROM supply.shipment_package p WHERE p.package_id=OLD.package_id AND p.central_legal IS NOT NULL);
 END IF;
 IF TG_OP <> 'DELETE' THEN
   owned := owned OR NEW.central_kind IS NOT NULL OR EXISTS(SELECT 1 FROM supply.shipment_package p WHERE p.package_id=NEW.package_id AND p.central_legal IS NOT NULL);
 END IF;
 IF owned AND (TG_OP<>'INSERT' OR current_setting('bsv.sup59_command',true) IS DISTINCT FROM '1') THEN
   RAISE EXCEPTION 'SUP59 managed movement is append-only via D command API' USING ERRCODE='23514';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END $$;
CREATE TRIGGER sup59_movement_guard BEFORE INSERT OR UPDATE OR DELETE ON supply.movement
 FOR EACH ROW EXECUTE FUNCTION supply.sup59_guard_movement();

-- Reference-only bindings for a D owner with no pre-existing lot/outbox tables.
-- For a real owner with existing tables, map these operations to that authority;
-- never create another lot or audit/outbox ledger. The fixture guard above applies.
CREATE TABLE supply.stock_lot (
 stock_lot_id text PRIMARY KEY, legal_entity_id text NOT NULL, material_id text NOT NULL,
 stock_location_id text NOT NULL, base_uom text NOT NULL,
 remaining_base numeric(18,4) NOT NULL CHECK(remaining_base>=0),
 received_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
 state text NOT NULL CHECK(state IN ('ACCEPTED','HOLD','SCRAPPED')),
 version integer NOT NULL CHECK(version>=1), opening_evidence_id text, CHECK(expires_at>received_at)
);
CREATE UNIQUE INDEX sup59_raw_opening_once ON supply.stock_lot(legal_entity_id,opening_evidence_id) WHERE opening_evidence_id IS NOT NULL;
CREATE SCHEMA event_audit;
CREATE TABLE event_audit.supply_event (
 audit_event_id uuid PRIMARY KEY, legal_entity_id text NOT NULL, actor_employee_id text NOT NULL,
 request_id uuid NOT NULL, operation text NOT NULL, occurred_at timestamptz NOT NULL,
 facts jsonb NOT NULL, UNIQUE(legal_entity_id,actor_employee_id,request_id)
);
CREATE TABLE event_audit.supply_outbox (
 sync_event_id uuid PRIMARY KEY, audit_event_id uuid NOT NULL UNIQUE REFERENCES event_audit.supply_event(audit_event_id),
 state text NOT NULL CHECK(state IN ('PENDING','DELIVERED')), created_at timestamptz NOT NULL
);

REVOKE ALL ON SCHEMA supply,event_audit FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA supply,event_audit FROM PUBLIC;
GRANT USAGE ON SCHEMA supply,event_audit TO bsv_supply_runtime;
GRANT SELECT,INSERT ON ALL TABLES IN SCHEMA supply TO bsv_supply_runtime;
GRANT UPDATE ON supply.shipment,supply.shipment_package,supply.stock_lot TO bsv_supply_runtime;
GRANT UPDATE(response) ON supply.idempotent_result TO bsv_supply_runtime;
GRANT SELECT,INSERT ON event_audit.supply_event,event_audit.supply_outbox TO bsv_supply_runtime;
COMMIT;
