-- SUP-59 executable PostgreSQL reference migration, ONLY for a disposable fixture.
-- Production requires mapping to the existing inventory owner and approved migration.
-- Extends the existing proposal: no second package, movement or idempotency ledger.
DO $$ BEGIN
 IF current_database() <> 'bsv_sup59_isolated_candidate'
 OR current_setting('bsv.sup59_schema_fixture', true) IS DISTINCT FROM 'yes'
 THEN RAISE EXCEPTION 'SUP59 candidate migration requires disposable fixture'; END IF;
END $$;
ALTER TABLE supply.shipment ADD COLUMN central_legal text,
 ADD COLUMN eta timestamptz, ADD COLUMN sent_at timestamptz,
 ADD COLUMN sender_id text, ADD COLUMN arrived_at timestamptz, ADD COLUMN dispatched jsonb;
ALTER TABLE supply.shipment_package ALTER COLUMN shipment_id DROP NOT NULL,
 ADD COLUMN central_legal text, ADD COLUMN stock_location_id text,
 ADD COLUMN remaining_base numeric(18,4), ADD COLUMN version integer,
 ADD COLUMN opened_at timestamptz, ADD COLUMN expires_at timestamptz,
 ADD COLUMN original jsonb, ADD COLUMN recall_reason text, ADD COLUMN recalled_at timestamptz,
 ADD CONSTRAINT sup59_package_facts CHECK (central_legal IS NULL OR
 (stock_location_id IS NOT NULL AND remaining_base IS NOT NULL AND remaining_base>=0
 AND remaining_base<=qty_base AND version IS NOT NULL AND version>=1 AND expires_at IS NOT NULL AND original IS NOT NULL));
CREATE INDEX sup59_stock_location ON supply.shipment_package(central_legal,stock_location_id,item_id);
ALTER TABLE supply.movement ADD COLUMN central_kind text;
CREATE TABLE supply.central_plan (
 plan_id uuid PRIMARY KEY, legal_entity_id text NOT NULL, source_location_id text NOT NULL,
 dest_location_id text NOT NULL, item_id text NOT NULL, facts jsonb NOT NULL,
 created_at timestamptz NOT NULL, CHECK(source_location_id<>dest_location_id));
CREATE TABLE supply.central_batch (
 batch_id uuid PRIMARY KEY, plan_id uuid NOT NULL UNIQUE REFERENCES supply.central_plan(plan_id),
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
 version integer NOT NULL CHECK(version>=1), CHECK(expires_at>received_at)
);
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
