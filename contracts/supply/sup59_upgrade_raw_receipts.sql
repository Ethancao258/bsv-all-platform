-- Incremental migration for a sole D ledger already initialized at c6346d3.
-- No role grants, new schema, row deletion, or first-ledger replay.
-- Production requires separately approved exact target/SHA, verified backup and C/D owner.
-- The custom approval reference is a technical guard, not approval in itself.
DO $migration$
BEGIN
 IF NOT (
   (current_database()='bsv_all_prod' AND current_user='bsv_supply_owner'
    AND nullif(current_setting('bsv.sup59_approval_ref',true),'') IS NOT NULL)
   OR (current_database()='bsv_sup59_isolated_candidate'
    AND current_setting('bsv.sup59_schema_fixture',true)='yes')
 ) IS TRUE THEN RAISE EXCEPTION 'approved SUP59 migration target required'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('BSV:SUP59:FIRST_LEDGER',0));
 IF to_regclass('supply.stock_lot') IS NULL
 OR to_regclass('supply.movement') IS NULL
 OR to_regclass('supply.sup59_raw_opening_once') IS NULL
 OR to_regclass('event_audit.supply_outbox') IS NULL
 THEN RAISE EXCEPTION 'existing D ledger must be verified'; END IF;
 IF current_database()='bsv_all_prod' AND NOT EXISTS (
    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='supply' AND c.relname='stock_lot'
    AND c.relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user)
 ) THEN RAISE EXCEPTION 'D table owner mismatch'; END IF;
 IF EXISTS (SELECT 1 FROM information_schema.columns
     WHERE table_schema='supply' AND table_name='stock_lot' AND column_name='purchase_receipt_ref')
 OR to_regclass('supply.sup59_raw_purchase_once') IS NOT NULL
 THEN RAISE EXCEPTION 'migration already applied or partial; verify existing type/index, do not replay'; END IF;
 ALTER TABLE supply.stock_lot ADD COLUMN purchase_receipt_ref text;
 CREATE UNIQUE INDEX sup59_raw_purchase_once ON supply.stock_lot(legal_entity_id,purchase_receipt_ref)
 WHERE purchase_receipt_ref IS NOT NULL;
END $migration$;
