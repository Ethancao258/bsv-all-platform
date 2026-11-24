# Isolated WorkBuddy catalog migrations

This directory holds numbered, checksummed migrations used only by the dedicated isolated catalog test database. `0001_workbuddy_v22.sql` is a reviewed candidate derived from the WorkBuddy V2.2 package; it is not a CloudBase official migration and not a record that any production schema has been applied.

The importer records the migration file SHA in `bsv_isolated_migration.applied`, rejects a checksum drift, and refuses to layer over pre-existing `catalog`, `core`, or `audit` tables without its own ledger. The SQL is applied transactionally to a blank isolated database. It contains no `DROP`, `TRUNCATE`, runtime auto-migration, sale approval, or inventory write.

Do not copy this file into `cloudbase/migrations/` or run it against CloudBase or a production DSN until the official CloudBase migration history, backups, restore path, permissions, and schema conflicts have been read and approved. Production DDL remains governed by the one official CloudBase migration ledger.
