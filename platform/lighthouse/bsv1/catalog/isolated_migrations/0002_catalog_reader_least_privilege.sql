-- Hardens the isolated catalog after 0001. Never use as a production CloudBase migration.
DO $$ BEGIN
  IF current_database() <> 'bsv_all_prod' THEN
    RAISE EXCEPTION 'catalog least-privilege migration is restricted to bsv_all_prod';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='bsv_catalog_reader') THEN
    RAISE EXCEPTION '0001 migration must be applied first';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='bsv_catalog_runtime' AND rolcanlogin
                 AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole) THEN
    RAISE EXCEPTION 'restricted bsv_catalog_runtime login must be provisioned by the isolated host';
  END IF;
  IF current_user <> (SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()) THEN
    RAISE EXCEPTION 'migration must run as the dedicated catalog database owner';
  END IF;
  IF NOT pg_has_role('bsv_catalog_runtime','bsv_catalog_reader','MEMBER')
     OR NOT pg_has_role('bsv_catalog_runtime','bsv_catalog_confidential_reader','MEMBER')
     OR (SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
         WHERE r.rolname='bsv_catalog_runtime') <> 2
     OR (SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
         WHERE r.rolname='bsv_catalog_importer') <> 0 THEN
    RAISE EXCEPTION 'catalog runtime and importer role memberships are not least-privilege';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='bsv_catalog_confidential_reader'
                 AND NOT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole) THEN
    RAISE EXCEPTION 'restricted non-login confidential reader role must be provisioned by the isolated host';
  END IF;
END $$;

ALTER TABLE audit.import_batch ADD COLUMN IF NOT EXISTS approval_id UUID;
ALTER TABLE audit.import_batch ADD COLUMN IF NOT EXISTS approver TEXT;
ALTER TABLE audit.import_batch ADD COLUMN IF NOT EXISTS change_id TEXT;
ALTER TABLE audit.import_batch ADD COLUMN IF NOT EXISTS manifest_sha256 CHAR(64);
ALTER TABLE audit.import_batch ADD COLUMN IF NOT EXISTS contract_sha256 CHAR(64);
ALTER TABLE audit.import_batch ADD COLUMN IF NOT EXISTS expected_active_source_sha256 CHAR(64);
ALTER TABLE audit.import_batch ADD COLUMN IF NOT EXISTS approval_hmac_sha256 CHAR(64);
CREATE TABLE IF NOT EXISTS audit.content_activation_event (
  event_id UUID PRIMARY KEY,
  source_sha256 CHAR(64) NOT NULL REFERENCES audit.import_batch(source_sha256),
  prior_source_sha256 CHAR(64) REFERENCES audit.import_batch(source_sha256),
  content_revision BIGINT NOT NULL,
  operation TEXT NOT NULL CHECK (operation IN ('IMPORT_RAW','ACTIVATE_RAW')),
  approval_id UUID NOT NULL,
  approver TEXT NOT NULL,
  change_id TEXT NOT NULL,
  approval_hmac_sha256 CHAR(64) NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 0001's broad grant is explicitly removed. Runtime roles receive narrow table columns
-- and filtered JSON views; raw formula, mapping, legal-path and calculation tables stay private.
REVOKE ALL ON ALL TABLES IN SCHEMA catalog, core, audit FROM bsv_catalog_reader;
REVOKE ALL ON ALL TABLES IN SCHEMA catalog, core, audit FROM bsv_catalog_confidential_reader;
GRANT USAGE ON SCHEMA catalog, audit TO bsv_catalog_reader, bsv_catalog_confidential_reader;

GRANT SELECT (product_id, name_zh, sales_series, category_l1, category_l2, category_l3, category_l4,
              ingest_status, _source_sha256)
  ON catalog.product TO bsv_catalog_reader;
GRANT SELECT (semifinished_id, name_zh, category_l1, category_l2, category_l3, category_l4,
              ingest_status, _source_sha256, content_review_status)
  ON catalog.semifinished TO bsv_catalog_reader;
GRANT SELECT (material_id, name_zh, category_l1, category_l2, category_l3, category_l4,
              ingest_status, _source_sha256)
  ON catalog.material TO bsv_catalog_reader;
GRANT SELECT (bundle_id, name_zh, category_l1, category_l2, category_l3, category_l4,
              ingest_status, _source_sha256)
  ON catalog.bundle TO bsv_catalog_reader;
GRANT SELECT (recipe_step_id, input_material_id, output_link_id, output_product_id,
              output_semifinished_id, _source_sha256)
  ON catalog.recipe_step TO bsv_catalog_reader;
GRANT SELECT (singleton_id, source_sha256, content_revision, activated_at, activation_status)
  ON catalog.active_content TO bsv_catalog_reader;
GRANT SELECT (source_sha256, package_version, status, imported_at)
  ON audit.import_batch TO bsv_catalog_reader;
GRANT SELECT (source_sha256, target_table, source_header_zh, permission_class)
  ON audit.field_dictionary TO bsv_catalog_reader;

CREATE OR REPLACE VIEW audit.source_record_staff WITH (security_barrier=true) AS
SELECT r.source_sha256, r.entity_table, r.record_id, r.excel_row,
       COALESCE(jsonb_object_agg(k.key, k.value) FILTER (WHERE d.permission_class IN ('PUBLIC','INTERNAL')), '{}'::jsonb) AS raw_fields
FROM audit.source_record r
CROSS JOIN LATERAL jsonb_each(r.raw_fields) k
LEFT JOIN LATERAL (
  SELECT CASE WHEN count(*)=0 THEN 'UNKNOWN'
              WHEN bool_or(permission_class='RESTRICTED') THEN 'RESTRICTED'
              WHEN bool_or(permission_class='CONFIDENTIAL') THEN 'CONFIDENTIAL'
              WHEN bool_or(permission_class='INTERNAL') THEN 'INTERNAL' ELSE 'PUBLIC' END AS permission_class
  FROM audit.field_dictionary
  WHERE source_sha256=r.source_sha256 AND target_table=r.entity_table AND source_header_zh=k.key
) d ON true
GROUP BY r.source_sha256, r.entity_table, r.record_id, r.excel_row;
CREATE OR REPLACE VIEW audit.source_record_confidential WITH (security_barrier=true) AS
SELECT r.source_sha256, r.entity_table, r.record_id, r.excel_row,
       COALESCE(jsonb_object_agg(k.key, k.value) FILTER (WHERE d.permission_class IN ('PUBLIC','INTERNAL','CONFIDENTIAL')), '{}'::jsonb) AS raw_fields
FROM audit.source_record r
CROSS JOIN LATERAL jsonb_each(r.raw_fields) k
LEFT JOIN LATERAL (
  SELECT CASE WHEN count(*)=0 THEN 'UNKNOWN'
              WHEN bool_or(permission_class='RESTRICTED') THEN 'RESTRICTED'
              WHEN bool_or(permission_class='CONFIDENTIAL') THEN 'CONFIDENTIAL'
              WHEN bool_or(permission_class='INTERNAL') THEN 'INTERNAL' ELSE 'PUBLIC' END AS permission_class
  FROM audit.field_dictionary
  WHERE source_sha256=r.source_sha256 AND target_table=r.entity_table AND source_header_zh=k.key
) d ON true
GROUP BY r.source_sha256, r.entity_table, r.record_id, r.excel_row;

GRANT SELECT ON audit.source_record_staff TO bsv_catalog_reader;
GRANT SELECT ON audit.source_record_confidential TO bsv_catalog_confidential_reader;
-- The importer alone writes. Read roles cannot execute DDL/DML or access raw payloads.
