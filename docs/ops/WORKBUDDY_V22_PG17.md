# WorkBuddy V2.2｜PG17隔离迁移与只读资料接入

状态：代码候选；隔离PG执行未完成；CloudBase官方迁移历史未核验；Lighthouse未连接。

## 数据和来源证明

- 外层交接ZIP SHA256：`d0b40f376880791a4feab9d8dff165c6b1a401db823781cb10da7da46cb95d3d`
- 内层 WorkBuddy V2.2 ZIP SHA256：`3f98fbe12eacdca481d1e7b3350a59410da7f1116c74a75a1c7b93fe63a0e5a1`
- 原 Excel SHA256：`4ed9bc164981f267997bd146dfd54d27ae22fbdc9cc1c850776daed83d34c8e82`
- 独立包验收工具：`47 PASS / 0 FAIL`；独立 SQL 结构工具：13张候选表、0项静态错误。上述只是输入包静态验证，不是 PG 执行结果。
- WorkBuddy `schema_proposal.sql` 仅供核对。独立隔离版本化迁移为 `platform/lighthouse/bsv1/catalog/isolated_migrations/0001_workbuddy_v22.sql`，不属于 `cloudbase/migrations/` 官方CloudBase历史，也不得直接用于正式数据库。

## 迁移要点

- `config/data-contracts.json` 继续是唯一语义/物理映射注册表；新增381项 WorkBuddy 字段定义，保留已有POS稳定API语义键。
- 迁移保留候选13表，并增加5张隔离导入支撑表（批次、当前原始资料版本、来源映射、字段字典、来源记录），一共18张。
- 主业务行按 `(永久业务ID, source_sha256)` 版本化。ID原样保留；新版本可并存，不覆盖历史行。只在导入事务全部校验后移动 `catalog.active_content` 指针。
- R制作行保留 `output_link_id` 原值，并用互斥的同版C/P外键约束：63条C成品、`R000048→P000003`、`R000051→P000004`。输入物料ID和套餐槽位继续为空，不猜测绑定。
- 原始行状态固定 `IMPORTED_RAW`。上架状态、有效报价、库存扣减都不会由导入触发。公式、缓存、来源映射及原字段值分别归档；缓存为空仍为空。
- 失败时数据与批次标记在同一个PG事务回滚；同SHA再次导入返回 `IDEMPOTENT_NOOP`；切回旧资料版本只更新 `catalog.active_content`，不删改新旧数据。
- POS PG读取仅在 `BSV_CATALOG_READ_SOURCE=postgres`、`BSV_APP_ENV=isolated` 且 `BSV_DB_URL` 为loopback时启用。Repository执行 `SET ROLE bsv_catalog_reader`、校验PG17、仅执行SELECT；PG不可用时资料API返回503，不回退到SQLite/Excel。订单、座位和支付快照仍使用原SQLite。

## 隔离服务器执行方式

本轮没有 Lighthouse Shell/TAT 授权，以下命令没有在真实主机运行。执行前必须确认使用**隔离PG实例和loopback端口**，目标库名 `bsv_all_prod`；不得使用既有 `bsv_identity_isolated_internal`，不得将正式CloudBase DSN传入导入器。导入器会拒绝非loopback、非隔离环境、非PG17、非目标库名，并拒绝覆盖已经存在但没有本迁移账本的 `catalog/core/audit` 表。

1. 将已核验的内层 `BSV_ALL_Excel标准数据包_V2.2.zip` 上传到仅服务账号可读的隔离 imports 目录并保留原件；解压到独立目录。不要将原包、Excel、实际SQL导出或凭据提交Git。
2. 在隔离主机上用管理员流程创建空的专用PG17数据库 `bsv_all_prod` 和最小导入/服务角色；本次未验证现有stage PostgreSQL能否安全承载该独立库，也未确认磁盘/WAL/备份容量。
3. 以受保护环境文件设定 `BSV_APP_ENV=isolated`、`BSV_ALLOW_ISOLATED_CATALOG_IMPORT=1`、`BSV_DB_URL=postgresql://<isolated-admin>@127.0.0.1:<isolated-port>/bsv_all_prod`。不把值写到命令行历史、终端输出或Git。
4. 运行锁定 `psycopg==3.2.13` 环境：

   ```bash
   python services/api/bsv1/bsv_catalog_import.py \
     --package-dir /var/lib/bsv-all-internal-stage/pos/imports/incoming/workbuddy-v22 \
     --archive /var/lib/bsv-all-internal-stage/pos/imports/incoming/BSV_ALL_Excel标准数据包_V2.2.zip
   ```

5. 首次必须见到 `status=COMMITTED_RAW`；再执行同一命令必须见到 `IDEMPOTENT_NOOP`。以输出的实际SQL计数和下列核验SQL为准：

   ```sql
   SELECT p.product_id, p.name_zh, p.ingest_status FROM catalog.product p
     JOIN catalog.active_content a ON p._source_sha256=a.source_sha256
     WHERE a.singleton_id=1 AND p.product_id='C000001';
   SELECT r.recipe_step_id, r.output_link_id, r.output_product_id, r.output_semifinished_id
     FROM catalog.recipe_step r JOIN catalog.active_content a ON r._source_sha256=a.source_sha256
     WHERE a.singleton_id=1 AND r.recipe_step_id IN ('R000048','R000051');
   SELECT count(*) FROM audit.excel_formula_index f
     JOIN catalog.active_content a ON f.source_sha256=a.source_sha256 WHERE a.singleton_id=1;
   ```

6. POS只读开关须经单独配置审查后才设为 `postgres`。运行服务账号需获准 `SET ROLE bsv_catalog_reader`。不得将本迁移视为生产CloudBase DDL或由应用启动自动执行。
7. 回退资料版本（保留两版行数据）：

   ```bash
   python services/api/bsv1/bsv_catalog_import.py --activate-source-sha <previous_64_char_source_sha256>
   ```

   该命令只切换原始资料读取指针，不回退程序、Schema、订单或已核准销售状态。数据库恢复需使用隔离备份流程，不能通过复制/替换PGDATA实现。

## 尚未获得的证据

- 本工作区没有运行中的Docker daemon、`psql`/`postgres`客户端或本地PG17；GitHub Actions新增加的PG17 job尚未运行，因此真实DDL/导入回执仍待CI。
- 完整V2.2包经本地SHA/字段契约核验，但未进入PG17；真实SQL计数、失败回滚、双版本和页面HTTP读验证待新的CI job或授权隔离主机执行。
- 服务器现有服务/磁盘/RAM/WAL/备份恢复、实例权限、浏览器HTTPS/隧道访问均未核查；现网 `18760–18764` 与 `8765/8767` 状态未知于本轮。
- 外部主机尚未创建独立目录/库、导入工作区、媒体文件或读取角色。没有真实浏览器运行证据。
