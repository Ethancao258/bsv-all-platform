# CloudBase PG｜现有中央主库维护入口

- 当前报告使用 CloudBase PostgreSQL 上海，已有10张商品表。没有直接连接实时实例，具体表名/约束/迁移版本未知。
- **唯一正式 DDL 账本**：CloudBase 官方 `cloudbase/migrations/<YYYYMMDDHHMMSS>_<name>.sql`；Codex通过MCP `queryPgDatabase` 只读盘点 → `managePgDatabase(dryRun / planMigration)` → 经授权 `applyMigration` → `listMigrations`核验。
- `migrationName` 应小写字母与下划线，`migrationVersion` 是14位时间戳；不要用本地自造的 `bsv_sys_migrations` 竞争平台官方迁移账本。
- `cloudbase/migrations/` 当前只有 README：**无任何生产迁移被本包执行或认定为已提交**。
- 优先保护原有十表和不确定字段，不凭模板运行前版候选的39/40表 DDL。正式迁移应由 Codex 实际读库后分业务域小步增量生成。
- 认证密码、Token、会话由平台 `auth` 管理；业务表只管理身份映射和授权。权限默认为拒绝，RLS+GRANT+服务端校验+安全日志。
