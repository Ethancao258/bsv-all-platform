# WorkBuddy V2.2｜PG17隔离迁移与只读资料接入

状态：代码候选；本地包重验通过；真实隔离PG执行和Lighthouse主机验收未执行；CloudBase官方迁移历史未核验。

## 数据和来源证明

- 外层交接ZIP SHA256：`d0b40f376880791a4feab9d8dff165c6b1a401db823781cb10da7da46cb95d3d`
- 内层 WorkBuddy V2.2 ZIP SHA256：`3f98fbe12eacdca481d1e7b3350a59410da7f1116c74a75a1c7b93fe63a0e5a1`
- 原 Excel SHA256：`4ed9bc164981f267997bd146dfd54d27ae22fbdc9cc1c850776daed83d34c8e82`
- 独立包验收工具：`47 PASS / 0 FAIL`；独立 SQL 结构工具：13张候选表、0项静态错误。上述只是输入包静态验证，不是 PG 执行结果。
- WorkBuddy `schema_proposal.sql` 仅供核对。独立隔离迁移为 `0001_workbuddy_v22.sql` 与 `0002_catalog_reader_least_privilege.sql`，不属于 `cloudbase/migrations/` 官方CloudBase历史，也不得直接用于正式数据库。

## 迁移要点

- `config/data-contracts.json` 继续是唯一语义/物理映射注册表；新增381项 WorkBuddy 字段定义，保留已有POS稳定API语义键。
- 迁移保留候选13表，并增加5张隔离导入支撑表（批次、当前原始资料版本、来源映射、字段字典、来源记录），一共18张。
- 主业务行按 `(永久业务ID, source_sha256)` 版本化。ID原样保留；新版本可并存，不覆盖历史行。只在导入事务全部校验后移动 `catalog.active_content` 指针。
- R制作行保留 `output_link_id` 原值，并用互斥的同版C/P外键约束：63条C成品、`R000048→P000003`、`R000051→P000004`。输入物料ID和套餐槽位继续为空，不猜测绑定。
- 原始行状态固定 `IMPORTED_RAW`。上架状态、有效报价、库存扣减都不会由导入触发。公式、缓存、来源映射及原字段值分别归档；缓存为空仍为空。
- 数据包清单提供逐文件SHA和记录数；导入器核实压缩包、解压目录、清单、工作簿SHA、实际数据行和当前语义契约。不再将V2.2 ZIP/XLSX SHA或记录数硬编码进程序，兼容的同契约内容版本可直接导入。
- 每次导入/资料版本回退必须提供24小时内的HMAC审批文件，绑定压缩包、清单、当前 `config/data-contracts.json`、来源SHA、操作者、变更号及审批时的活动版本；活动版本并发变化时拒绝。审批由隔离主机的root账户签发，密钥 `catalog-approval.key` 不进入POS服务环境。
- 失败时数据、审批审计和版本指针在同一个PG事务回滚；同SHA再次导入返回 `IDEMPOTENT_NOOP`；经独立审批切回旧资料版本只更新 `catalog.active_content`，不删改新旧行。
- PG迁移 `0002` 撤销 `0001` 的宽泛读授权，POS基础/配方读取改走字段权限过滤视图；`RESTRICTED` 原始采购价不会通过POS读取角色返回。原始审计表、公式表、映射表不授给POS读取角色。`bsv_catalog_runtime` 与 `bsv_catalog_importer` 分离，后者为专用 `bsv_all_prod` owner；POS专用 `pos.env` 才配置 `BSV_DB_URL`。身份继续用 `BSV_DB_A_URL` 指向 `bsv_identity_isolated_internal`。
- PG17 HBA只给两个catalog登录角色开放本机 `127.0.0.1/32`。受管升级只接受已知旧策略或精确新策略，先备份原HBA、写入并校验PostgreSQL规则；策略漂移或验证失败则拒绝或恢复。POS PG读取仅在隔离环境和 `BSV_CATALOG_READ_SOURCE=postgres` 时启用，PG不可用时API返回503，不回退到SQLite/Excel。订单、座位和支付快照仍使用原SQLite。
- catalog备份使用与身份备份相同的AES-256-GCM加密工具，但使用独立私有目录和独立密钥；目前恢复检查是认证解密的无写入核验，实际恢复到临时PG数据库仍需主机验收。

## 隔离服务器执行方式

本轮没有 Lighthouse Shell/TAT 授权，以下命令没有在真实主机运行。执行前必须确认使用**隔离PG实例和loopback端口**，目标库名 `bsv_all_prod`；不得使用既有 `bsv_identity_isolated_internal`，不得将正式CloudBase DSN传入导入器。导入器会拒绝非loopback、非隔离环境、非PG17、非目标库名，并拒绝覆盖已经存在但没有本迁移账本的 `catalog/core/audit` 表。

1. 受控部署器在现有隔离PG17 cluster内建立独立逻辑库 `bsv_all_prod`、`bsv_catalog_runtime` / `bsv_catalog_importer`，仅POS环境持有runtime DSN。它不会把身份数据库改名/改所有权。未知HBA或数据库owner变化都会拒绝升级。
2. 将原内层ZIP及解压目录上传至隔离 imports 目录并保留原件。不要将原包、Excel、真实SQL导出或凭据提交Git。运行 `bsv_catalog_import.py --package-dir ... --archive ...` 的包校验；当前完整包在本地重验得到 C63/P17/M419/K21/槽位21/NPS84/R65/Q0/T4、映射16815、字段381、公式6275、raw source record 694。此为包证据，不是数据库导入结果。
3. 使用root受保护的环境文件加载独立导入账户与审批密钥（不打印或复制DSN）：

   ```bash
   set -a
   . /opt/bsv-all-internal-stage/config/catalog-import.env
   set +a
   ```

4. 人工核对活动来源SHA（首次为空）及变更号后，签发绑定完整ZIP和清单的短期审批，并导入：

   ```bash
   /opt/bsv-all-internal-stage/current/identity/bin/python \
     /opt/bsv-all-internal-stage/current/src/services/api/bsv1/bsv_catalog_import.py \
     --package-dir <受控解压目录> --archive <内层ZIP> --issue-approval \
     --approver <企业操作者ID> --change-id <审批单或Issue编号> \
     --expected-active-source-sha <当前活动来源SHA；首次导入省略> \
     --approval-output <受控目录>/catalog-approval.json
   /opt/bsv-all-internal-stage/current/identity/bin/python \
     /opt/bsv-all-internal-stage/current/src/services/api/bsv1/bsv_catalog_import.py \
     --package-dir <受控解压目录> --archive <内层ZIP> --approval <同一审批文件>
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

6. POS只读接口应返回 `source.source=postgresql` 与实际活动SHA。匿名访问拒绝；配方按身份权限读取；采购受限字段不出现在POS响应。不得将本迁移视为生产CloudBase DDL或由应用启动自动执行。
7. 回退资料版本（保留两版行数据）也必须先签发 `activate` 审批，提交目标包、当前活动SHA、操作者和变更号，再把该审批传给回退命令。不再允许只凭SHA切换活动版本：

   ```bash
   /opt/bsv-all-internal-stage/current/identity/bin/python \
     /opt/bsv-all-internal-stage/current/src/services/api/bsv1/bsv_catalog_import.py \
     --package-dir <目标来源包解压目录> --archive <目标来源ZIP> --issue-approval \
     --approval-action activate --approver <当前sudo登录名> --change-id <审批单或Issue编号> \
     --expected-active-source-sha <当前活动来源SHA> --approval-output <受控目录>/catalog-rollback-approval.json
   /opt/bsv-all-internal-stage/current/identity/bin/python \
     /opt/bsv-all-internal-stage/current/src/services/api/bsv1/bsv_catalog_import.py \
     --activate-source-sha <previous_64_char_source_sha256> \
     --activation-package-dir <目标来源包解压目录> --archive <目标来源ZIP> \
     --approval <受控目录>/catalog-rollback-approval.json
   ```

   该命令只切换原始资料读取指针，不回退程序、Schema、订单或已核准销售状态。数据库恢复需使用隔离备份流程，不能通过复制/替换PGDATA实现。

## 尚未获得的证据

- 本工作区没有可用的Docker daemon或本地PG17，也没有Lighthouse/TAT/SSH授权；本地PG17测试被跳过，待GitHub Actions的真实PG17容器job验证DDL及HTTP读权限。
- 完整V2.2包经本地SHA/字段契约核验，但未进入PG17；真实SQL计数、失败回滚、双版本和页面HTTP读验证待新的CI job或授权隔离主机执行。
- 服务器现有服务/磁盘/RAM/WAL/加密备份实际恢复、数据库角色、浏览器SSH隧道读取均未核查；现网 `18760–18764` 与 `8765/8767` 状态未由本轮工具读取。
- 外部主机尚未创建/核查本任务数据库及导入目录，完整真实资料未入库，POS网页未验证实际来自PostgreSQL。没有真实浏览器证据。CloudBase生产数据、员工主库、订单及会员交易均未连接。
