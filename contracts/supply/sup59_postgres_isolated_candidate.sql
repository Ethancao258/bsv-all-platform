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
