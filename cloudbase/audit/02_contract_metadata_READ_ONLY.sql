-- G0 only. Run one SELECT at a time through authorized queryPgDatabase.
-- Metadata only. Do not query business rows or secrets.
SELECT n.nspname AS schema_name,c.relname AS table_name,con.conname,
       con.contype,pg_get_constraintdef(con.oid,true) AS definition
FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid
JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%'
ORDER BY 1,2,3;

SELECT n.nspname AS schema_name,c.relname AS table_name,
       c.relrowsecurity,c.relforcerowsecurity,pg_get_userbyid(c.relowner) AS owner_role
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE c.relkind IN ('r','p') AND n.nspname NOT IN ('pg_catalog','information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
ORDER BY 1,2;

SELECT schemaname,tablename,indexname,indexdef FROM pg_indexes
WHERE schemaname NOT IN ('pg_catalog','information_schema') AND schemaname NOT LIKE 'pg_toast%'
ORDER BY 1,2,3;

SELECT event_object_schema, event_object_table, trigger_name, event_manipulation, action_timing
FROM information_schema.triggers ORDER BY 1,2,3,4;

SELECT table_schema,table_name,grantee,privilege_type
FROM information_schema.table_privileges
WHERE table_schema NOT IN ('pg_catalog','information_schema')
ORDER BY 1,2,3,4;
