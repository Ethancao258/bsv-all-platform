# POS-06｜总部商品数据库维护 Architecture V1.0
DESIGN_READY / 未实施。固定路线 POS-06，对应 Issue #41 B01/B02/B03。BASE=2052ef51f011be3c5898d816932d8982f420b752 已核查历史源码；现网增量优先。先完成网页 Excel 更新，再做行级编辑；可与 POS-05/07 并行编码，正式接管遵守 Issue #41 A 阶段验收。不要重写商品主库或身份系统。
## 1 已有资产、准确入口与数据库
- config/data-contracts.json：七页 C/P/M/K/R/Q/T 的字段字典、语义字段、权限类别、NULL/单位/来源；config/data-ownership.json 为所有权权威。
- services/api/shared/data_contracts.py::resolve_database（29-71）：中央 BSV_DB_URL、PostgreSQL 17、bsv_all_prod，正式迁移 owner cloudbase/migrations。禁止将 POS SQLite/旧身份库当中央写库。生产配置尚非全部验收。
- services/api/bsv1/bsv_catalog_repository.py::PostgresCatalogReadRepository（85起）：_connection 显式 SET ROLE bsv_catalog_reader 或 bsv_catalog_confidential_reader，_active（117附近）读取 catalog.active_content 联合 audit.import_batch；_source_fields 按 entity_table、record_id、source_sha256 读 audit.source_record_staff/confidential。读角色不得升权。
- services/api/bsv1/bsv_catalog_contract.py：postgres_field、semantic_attributes；services/api/bsv1/bsv_v9_import.py：cents_from_price、price_is_current、catalog_for_store；旧 SQLite 全量导入不得拿来重建 PG 或直接清理历史订单引用。
- platform/lighthouse/bsv1/catalog/isolated_migrations/0001_workbuddy_v22.sql（1068行）：候选版 DDL。已经存在版本化表/指针，无需另建主库。实际 WorkBuddy V2.2 导入器的入口尚未定位，优先在现有 platform/lighthouse/bsv1/catalog、ingestion、scripts、tools 及保留的导入工程中按 import_batch/COMMITTED_RAW 查找；不得把下列候选接口声称为已有代码。
- 当前服务器已有 tools/sync_pg_catalog.py（本轮日志可见，非 BASE 文件）；它是 PG→SQLite 投影，不是 Excel→PG 导入器。必须核查实际分页、授权及版本一致性；T门店审批不得取旧 SQLite 伪造正式许可。
- 总部原生页面实际在 apps/hq-console/identity，身份服务 services/api/identity/api.py:31-45、219-220 路由 /hq 和 /hq-assets/hq.js；另有 POS 地图管理 apps/store-console/bsv1 的 hq 资源，勿混淆。新增商品维护用总部工作台链接和独立子页面，不重建 HQ 登录。
- Issue #41、PR #40 为阶段B和PG读取历史依据，PR #39 CloudBase拉取候选可复用校验/快照，但 CloudBase 不是第二权威写库。
## 2 解除普通 shell 环境阻塞
普通 shell 没有 BSV_DB_URL 是正常现象；不要索要/输出 DSN。实际 systemd 是模板单元，查看 systemctl cat bsv-all-internal-stage@pos.service（注意脱敏）或 systemctl show -p EnvironmentFiles -p User -p FragmentPath bsv-all-internal-stage@pos.service，不读取全量 Environment；实际路径以 current 解析。已有服务使用受保护 EnvironmentFile。只读探针通过 sudo -n systemd-run --wait --pipe --collect、现有 EnvironmentFile、服务用户及锁定 Python 运行，仅输出 SELECT current_database()、server_version_num、是否具备所需权限和活动版本；不输出 DSN/密码，探针退出清理。导入器另用最小写入角色及独立受保护配置，复用历史 catalog importer 角色/流程（存在则验证），绝不把写权限授给 POS reader 或普通员工。现有 sync 工具头部已有 systemd-run 示例，先读它，不再重复连接调查。不要把真实配置写进公开 repo。
## 3 已有 PG 表映射（BASE DDL）
C→catalog.product；P→catalog.semifinished；M→catalog.material；K→catalog.bundle（另有 bundle_slot、store_nps）；R→catalog.recipe_step；Q→catalog.price_quote；T→core.store。具体拆分以 registry/source_mapping 为准，不猜测派生行。实体按固定ID+_source_sha256版本保存，R的输出C/P及输入M、K槽及门店关联使用同版本FK。
audit.import_batch(batch_id,source_sha256 UNIQUE,package_sha256,package_version,status COMMITTED_RAW,counts,imported_at)；catalog.active_content(singleton_id=1,source_sha256 FK,content_revision,activated_at,activation_status IMPORTED_RAW)；audit.source_mapping、field_dictionary、source_record（source_sha256/entity_table/record_id,excel_row,raw_fields）；audit.excel_formula_index 等。保留原始数据与公式索引，活动指针与销售审批分离。无需重建已有 schema。历史版本不可覆盖；新增字段走官方增量迁移。
## 4 NEW 候选实现（有原实现则直接扩展）
独立 catalog-admin service 或现有 owner 的受控模块；复用 /hq 身份会话，注册 catalog.upload/preview/approve/publish/rollback/price.approve 动作至身份 A（名称候选，先查 registry），不能借用地图权限或 POS 下单权限。跨服务用限定 service token、bearer session、CSRF；每个操作核验法人/HQ 范围、不同审核人。网关显式路由 /api/v1/catalog/admin/，不得落入泛 identity 或普通 POS 只读路径。
候选 API：
POST /api/v1/catalog/admin/imports 上传 .xlsx，返回 import_id/hash/状态；GET /{id}/preview 差异与精确工作表行列错误；POST /{id}/approve 和 /publish（expected_revision、request_id、批准摘要）；GET /versions；POST /versions/{sha}/activate（回滚也双审和CAS）；后续 POST /drafts 等走同一变更服务。
候选 audit.catalog_change_request / change_review / activation_event：id/source_sha/package_sha/base_revision/creator/approver/status/diff_hash/validation_result/created_at；事件记录 from_sha/to_sha/revision/reason/actor；唯一 request_id、版本并发保护。保留原 import_batch 的 COMMITTED_RAW 语义，不在其中塞假审批状态。
## 5 最短提交算法
1 上传只进受控私有隔离目录；大小/解压资源限制、文件类型/zip路径/外链/宏/恶意内容检查，失败不激活；不将原始 Excel 发公共 GitHub 或外部沙箱。复用 WorkBuddy V2.2 解析和验证器，保留原始文件 SHA256、规范化包 SHA256、字典版本；如验证器暂时找不到先实现兼容适配，不冒充原实现。公式读取 formula 与 data_only 双视图，缺失必要缓存/不支持公式/单位未知直接报错，不猜结果；不执行外链或宏。
2 校验固定ID前缀、唯一性、同一实体冲突、所有引用、数据类型/单位/权限、Q报价及T门店；空保持 NULL。对比当前 active SHA 的同ID同语义字段：ADD/CHANGE/UNCHANGED/PENDING_RETIRE/CONFLICT。新文件缺行不是删除；拟停用需审批，构建完整候选快照时保留未批准退役的历史有效实体和关联，原始上传与合成有效快照须独立 hash/溯源，不能假称原文件 hash 对应修改后内容。首版若无法安全保留缺行，则阻止激活并给出具体错误。
3 发码优先复用既有 allocator（未定位则新增候选 catalog owner allocator，按前缀事务锁/唯一约束，初始化核对所有历史ID的最大已分配编号和保留范围；永不重用已发ID，允许空洞）。不得按 Excel 行号/名称产生新ID。
4 审核者看到差异、公式缺口、引用、价格和停售影响；确认对象为不可变候选 hash + base revision。并发变化返回409要求重做预览。相同来源及同策略重复提交 IDEMPOTENT_NOOP，若只是请求激活已存在历史SHA则按显式回滚审批处理。
5 PG 一事务：锁 singleton active_content FOR UPDATE（首次初始化用唯一约束/迁移预置）；核对 expected_revision；插入完整版本化实体、字典/公式/来源及 import_batch（FK顺序以实际DDL）；核对计数、所有链接、source SHA；写激活事件并更新活动指针 content_revision+1；任一步失败整笔回滚。禁止先激活再填表。商品原始资料生效≠获准销售；AS/AX/T/Q及已有价格规则独立批准。Q为空不得真实收款；AJ仅标注参考或批准政策范围内的价格，不自动核准，不用统一价格覆盖真实门店差异。
6 投影同步：从同一个已提交的 source_sha/revision 一致性快照读取完整C/K/批准状态等（不是先读分页搜索再猜全量）；按权威 counts/唯一ID/关联校验，失败不覆盖；SQLite 单事务 upsert 固定ID与版本、停用不删除历史引用，记录 active projection revision；草稿在版本/售价变化后重新确认，已成交快照不变。PG激活后投影失败，显示“资料已更新、点单投影待同步”，阻止使用不一致版本的新订单，保留历史查询；重试幂等，不能假称全部同步成功。回滚原版本仅切指针并递增 revision，重新同步；不删除新旧历史。
## 6 06.01-08 实施及验收
06.01上传页面→02校验→03差异预览→04发码→05审核/版本→06原子发布→07投影同步→08回滚/审计。UI 上传→具体差异/错误→批准→确认生效→商品页显示同 revision；可视化编辑复用同一候选/审核/发布路径，后续实现。
隔离验收：同模板增加一条测试商品、修改一条R工序，通过浏览器上传、审核、激活，POS按固定ID/拼音读取同版本；未批不售；同SHA重复不改版本；非法模板、缺行、公式缓存缺失、重复ID、断链、旧预览、越权/跨法人全部拒绝；投影失败不损坏订单；回滚后原版可见，成交价不变。真实批准/生产写入须经营者授权；先用隔离数据完成功能。正式发布按现有增量机制，从当前有效代码建独立 worktree，禁止覆盖旧SHA目录。报告实际导入器、schema/roles（无秘密）、接口、浏览器结果、部署版本和待审批。