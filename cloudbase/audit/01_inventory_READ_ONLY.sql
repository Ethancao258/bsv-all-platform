-- V2.0只读元数据盘点：人工审核后才通过CloudBase queryPgDatabase执行。
-- 不调用写入语句。限制返回，不查询会员/员工/密码等敏感行。
SELECT current_database() AS db_name, current_schema() AS current_schema, version() AS pg_version;
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_type = 'BASE TABLE' AND table_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY table_schema, table_name;
SELECT table_schema, table_name, column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name LIKE 'bsv_%'
ORDER BY table_name, ordinal_position;
SELECT schemaname, tablename, policyname, cmd, roles
FROM pg_policies WHERE schemaname = 'public'
ORDER BY tablename, policyname;
-- 迁移历史使用官方 managePgDatabase(listMigrations)，不得猜系统迁移表名。
