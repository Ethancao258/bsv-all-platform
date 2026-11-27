# HQ-CATALOG-01｜总部商品与数据库管理中心：部署接管唯一入口（#63 / PR #64）

状态：SOURCE_CANDIDATE / PRODUCTION_BLOCKED。此文替代旧版适配器说明。必须在 #58 唯一集成工作树增量接入，不解冻 #44 A/B，不阻断M1。GitHub公开仓库只含代码、合成测试和契约，不放经营资料、凭据、员工信息。真实主机没有由GitHub端验证。

## 1. 产品入口与真实状态
- / → 业务 → 总部商品与数据库；/hq → 商品与数据库；/hq/catalog 为唯一页面；API /api/v1/hq/catalog/* 属于原 identity 服务，不开新端口。
- C现场成品、P预调、M采购/供货、K套餐、R配方、Q报价、T门店（只读）。检索、分页、字段分权、永久ID预留、网页新增/改名/改配方草稿、Excel预览、异人审核、候选规范包、历史版本与恢复申请。
- 状态必须逐级：PENDING_REVIEW → REVIEWED_NOT_PUBLISHED → VERIFIED_PACKAGE_NOT_PUBLISHED → RELEASE_REQUESTED → RAW_REVISION_ACTIVE。恢复申请无需生成新包，必须使用已存在的原始目标包。退役申请当前只登记，不删除。
- RAW_REVISION_ACTIVE 只表示PG原始目录活动版本，不等于销售审批或POS价格已变。禁止设置销售自动放行、伪造AS/AX/Q审批。现有POS SQLite交易、客户、地图、收款、库存账本保持原样。

## 2. 部署前检查与停止条件
1. C核对现有运行SHA、#58状态、实际进程环境和源码；独立worktree以当前正式候选为基线增量合并PR #64。不得用PR #64基线替换现场私有补丁。记录完整Git SHA；有冲突仅保留两线有效功能。
2. 核对原 identity.A 与 catalog PG17 实际连接和角色。现有 bsv_catalog_import.py 只接受精确已登记的**隔离**catalog数据库结构，现有身份库单独维持。绝不能为了通过预检改名数据库、删schema、移除迁移账本或将正式经营库冒充隔离库。
3. 保全原始WorkBuddy ZIP、原始Excel、当前活动PG源SHA及所有历史Excel/包，执行原加密备份流程，验证可恢复。身份与商品数据库各自配置不变。暂停其他目录同步写入者（包括自动Excel/CloudBase同步）直到本轮验收结束；不能影响营业订单。
4. 先在候选环境运行 bash tests/bsv1/check.sh、bash tests/identity/check.sh、tests/bsv1/catalog_pg17.sh 以及内部stage现有验收。PR最新HEAD的CI未通过或未完成则不得标记已验收；外部软件源安装失败单独记录并重试该步骤。不能凭历史CI放行新提交。

## 3. 环境配置（沿用原identity service；变量名固定）
在现有内部候选身份服务环境文件增量添加，不打印真实值，不修改 BSV_DB_A_URL：
- BSV_HQ_CATALOG_ENABLE=1；BSV_APP_ENV=isolated（只在隔离候选）。
- BSV_HQ_CATALOG_LEGAL_ENTITY_ID：已核验的候选法人，不自动授予真实公司权限。
- BSV_HQ_CATALOG_READ_DB_URL：原 bsv_catalog_runtime 同库PG17只读连接，loopback、数据库名 bsv_all_prod；禁止用导入owner。不要把此值赋给 BSV_DB_URL，否则破坏隔离身份配置。
- BSV_IMPORT_ROOT：现有受控导入根目录、由身份服务账号拥有、0700。草稿、私有候选包、永久ID账本、原始Excel均在其 hq-catalog-drafts 子目录，不是第二主库。目录须处于服务器加密存储并纳入现有备份。
- BSV_CATALOG_DIR：原有受管Excel版本目录；原始文件可从 versions/<源SHA>.xlsx 或草稿目录同名归档读取。HQ只按PG活动SHA选择原始文件，不修改旧POS current.json。
- BSV_HQ_CATALOG_SCANNER：受审的本机扫描器绝对路径，输入文件路径，退出0才允许，无扫描器拒绝上传。隔离网关默认4MiB，不扩大全站限制。
- BSV_HQ_CATALOG_ID_HISTORY_VERIFIED=1：仅在实际核对PG全部历史版本、旧Excel/旧系统已用ID、未生效但预留ID、既有永久ID分配规则后启用；在 hq-catalog-drafts/verified-legacy-ids.json 写入 {"status":"HISTORY_RECONCILED","evidence_ref":"私有核验记录索引","ids":[实际已使用历史ID]}，0600。不得填假清单或用当前最大ID代替历史核验。永久预留账本必须备份，不可删除重置。
- BSV_HQ_CATALOG_CONVERTER 可选；默认使用仓库 bsv_hq_workbook_package.py（381项注册字段、原文件、公式文字及缓存、业务表/辅助表/来源映射、哈希清单、已有导入器复核）。如果原WorkBuddy生成器已经在服务器可用，允许配置其审查后的绝对路径适配原参数 --baseline --draft --output [--candidate]，不得把未验证产物交给签名器。
- 真实工作簿含公式时，内置直接XML编辑器会拒绝以旧缓存生成网页变更；现有Excel上传可保持公式表达式原样并带Excel已保存缓存。需要可信的公式重算路径和独立公式审核，未接通不得声称所有网页编辑可直接生效。原始公式缓存为空仍保持空，不补零。

通过原总部权限管理申请并独立审批：hq.catalog.read；hq.catalog.confidential（配方/受控字段）；hq.catalog.draft；hq.catalog.review；hq.catalog.release.request。均为HQ法人级，不能从地图/门店权限推导。不自动给现有所有BM。草稿提交及审核还需 confidential；读权限单独不返回机密。原授权不改。

## 4. 原始规范包核验
先在私有临时目录用本仓库 identity venv Python 运行：
  PYTHONPATH="$REPO:$REPO/services/api/bsv1" "$PYTHON" -c 'from bsv_hq_workbook_package import make_package; from pathlib import Path; import sys; make_package(Path(sys.argv[1]),Path(sys.argv[2]))' "$BASELINE_XLSX" "$PRIVATE_EMPTY_OUTPUT_DIR"
将生成包与现有已审核WorkBuddy包逐表、逐字段、公式及原始SHA比对；真实基线中辅助映射和派生行键可能与旧生成器不同，未核实前仅候选。字段契约不符先停，不自行猜测。此程序不会执行SQL，不覆盖任何数据。
公式、K槽位/NPS子区、审批/上架状态、T门店主数据变化均有门禁：缺行不等于删除；当前公式结构与K子区修改不得从普通Excel发布，必须独立审核。需要正式处理K槽位等原本未绑定业务数据时应在现有表与契约上增量实现，不能造第二套套餐主表。

## 5. 受控发布/恢复命令（隔离数据；非生产）
网页：提交草稿 → 另一位有权限的TR审核 → 生成候选规范包 → 审核人点击申请资料生效。回退：查看历史版本 → 选择历史SHA → 提交恢复申请 → 异人审核 → 申请生效。
独立操作账号（原签发人/root）使用原受保护 catalog-import.env 和核验后的 identity.A 环境。不要把 BSV_CATALOG_ADMIN_DB_URL 或 BSV_CATALOG_APPROVAL_KEY_FILE 放进网页进程。BSV_ALLOW_ISOLATED_CATALOG_IMPORT=1 仅在已批准的隔离任务设置。现有审批私有目录0700，与网页草稿目录分离。
命令：
  "$PYTHON" "$REPO/services/api/bsv1/bsv_hq_release.py" --draft-root "$DRAFT_ROOT" --draft-id "$DRAFT_ID" --approval-dir "$PRIVATE_APPROVAL_DIR" --catalog-dir "$BSV_CATALOG_DIR"
预检成功输出 PREFLIGHT_OK_NOT_APPLIED；根据网页审核和实际隔离源SHA，经负责人授权后同命令添加 --apply --confirm-isolated "$EXPECTED_ACTIVE_SHA"。
恢复时额外传 --rollback-archive "$EXISTING_TARGET_WORKBUDDY_ZIP"。该ZIP必须对应历史源SHA；不生成伪造旧包。
执行器重新核验两个TR当前权限、法人、活动SHA、原始文件、包与清单；复制到签发人私有临时目录；复用现有create_approval、import_package或activate_source_revision；确认PG活动SHA后写回执。仅更新原始PG版本，不修改POS SQLite或current.json。异常时不盲重试，先核查audit.import_batch/content_activation_event及实际活动SHA；如果PG已经生效但回执失败，先恢复/补齐审核回执，绝不二次写入。
本版仍保留原人工签发边界；尚未实现无服务器操作的正式生产自动发布执行器，不得把root签发改成网页进程可调用的任意命令。后续经安全审批的服务化执行应复用这个精确执行器、固定参数、隔离角色、原密钥归属，不给网页任何PG owner能力。

## 6. 验收与回退
现场至少完成：未授权拒绝、只有读取权限无机密值、真实目录SHA一致、同人审批拒绝、异人审核通过、历史ID重用拒绝、重复Excel幂等、无扫描器拒绝、未知模板拒绝、合法候选生成、签名预检、隔离资料提交及旧版恢复、重启后实际活动SHA一致。检查POS旧交易数据、金额、权限和销售审批未变；单独用获准销售投影完成门店真实浏览器验证。直接编辑含公式真实模板、套餐槽位、退役、自动签名、正式PG共享schema迁移及消费者投影均不能当作已通过。
回退程序：在C唯一工作树恢复旧代码配置并关闭 BSV_HQ_CATALOG_ENABLE；不删除历史源、签名、预留ID或业务数据。资料回退必须使用上面独立签名激活旧版，订单和收款不可回退覆盖。
最终回执：BASE_SHA、HEAD_SHA、实际运行SHA、CI/浏览器证据、活动源SHA（非敏感）、是否保持销售投影不变、未完成阻断、回退记录。未满足正式上线条件一律 RELEASE_BLOCKED，停止，不开新项目。
