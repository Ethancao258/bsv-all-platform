-- Adds the narrow ordering-column read needed for recipe history retrieval.
-- Isolated PostgreSQL 17 only; this is not a CloudBase production migration.
DO $$ BEGIN
  IF current_database() <> 'bsv_all_prod' THEN
    RAISE EXCEPTION 'recipe ordering grant is restricted to bsv_all_prod';
  END IF;
  IF current_user <> (SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()) THEN
    RAISE EXCEPTION 'recipe ordering grant requires the dedicated catalog database owner';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='bsv_catalog_reader' AND NOT rolcanlogin
                 AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole) THEN
    RAISE EXCEPTION 'restricted catalog reader role is required';
  END IF;
END $$;

GRANT SELECT (_excel_row) ON catalog.recipe_step TO bsv_catalog_reader;
