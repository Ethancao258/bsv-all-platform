-- Apply once by approved deployment owner, never on application startup.
BEGIN;
DO $$ BEGIN
 IF current_database()<>'bsv_all_prod' OR current_setting('server_version_num')::int/10000<>17
 OR to_regclass('catalog.active_content') IS NULL OR to_regclass('audit.import_batch') IS NULL
 OR NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='bsv_catalog_importer')
 THEN RAISE EXCEPTION 'registered PG17 catalog required'; END IF;
END $$;
CREATE TABLE IF NOT EXISTS catalog.sale_release (
 release_id UUID PRIMARY KEY,
 source_sha256 CHAR(64) NOT NULL REFERENCES audit.import_batch(source_sha256),
 previous_release_id UUID REFERENCES catalog.sale_release(release_id),
 draft_id TEXT NOT NULL UNIQUE CHECK(draft_id ~ '^[a-f0-9]{32}$'),
 created_by TEXT NOT NULL, reviewed_by TEXT NOT NULL CHECK(reviewed_by<>created_by),
 legal_entity_id TEXT NOT NULL,
 decisions JSONB NOT NULL CHECK(jsonb_typeof(decisions)='object'),
 items JSONB NOT NULL CHECK(jsonb_typeof(items)='object'),
 status TEXT NOT NULL CHECK(status IN ('PENDING_PROJECTION','ACTIVE','SUPERSEDED')),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), activated_at TIMESTAMPTZ,
 CHECK(status='PENDING_PROJECTION' OR activated_at IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS sale_single_active ON catalog.sale_release((1)) WHERE status='ACTIVE';
CREATE UNIQUE INDEX IF NOT EXISTS sale_single_pending ON catalog.sale_release((1)) WHERE status='PENDING_PROJECTION';
REVOKE ALL ON catalog.sale_release FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON catalog.sale_release TO bsv_catalog_importer;
GRANT SELECT (release_id,source_sha256,status,activated_at,items) ON catalog.sale_release TO bsv_catalog_reader;
COMMIT;
