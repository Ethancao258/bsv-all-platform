# 只读检查，不自动在任何数据库执行

`01_inventory_READ_ONLY.sql` 是供 Codex 参考的PG元数据只读查询，真实环境优先通过 MCP `queryPgDatabase(action=objects/metadata/schema)` 调用，权限不允许时只记录错误，不要擅自升级角色。
