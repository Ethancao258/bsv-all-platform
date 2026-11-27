# HQ-CATALOG-01 V3｜正式经营上线执行单（#63 / PR #64）
**本文件是唯一当前执行入口，覆盖旧 HQ_CATALOG_CENTER.md 的隔离目标。** 交付目标不是另一个候选网页，而是经营者可在原企业域名登录、修改商品、更新真实中央PG、核准销售及同步现用POS和顾客酒单。保持 #44 停止边界及 #58 C唯一集成写入人。旧文档仅供历史/测试参考。

## A. 一次性接管现有经营环境
1. C在唯一现有集成工作树增量合入本PR的完整HEAD。保留C已经落地的正式HTTPS身份、设备、收款、订单、报表、代理及其他模块补丁；尤其 services/api/bsv1/app.py 只合并本PR的PG目录启动保护，不能覆盖C已修复的登录/Origin/收款。不得替换现用部署根目录或新建独立业务应用。记录实际合并SHA。
2. 确认实际正在服务的 admin.bsvm.cn 的统一工作台、identity.A、POS进程配置/SQLite路径、现有顾客菜单页面加载的HTTPS JSON地址与源站实际文件。用当前服务PID/启动配置、实际网页请求验证，不猜路径。当前企业域名、二维码、顾客酒单设计和会员路径不变。必须保留C已经验收的真实认证；若原provider仍是isolated，先按#58完成正式身份接管，不假冒生产、不启用旧预览口令作为员工身份。
3. 目标唯一商品主库是本服务器 PostgreSQL17 bsv_all_prod。使用已注册的catalog/core/audit及迁移账本；不另建总部商品数据库。若实际中央库已含原0001/0002/0003登记对象及相同校验值，直接复用。若真实资料仍在原候选目录，按原包、实际行数、版本SHA和备份执行一次受控接管；有现存同名关系冲突不得直接套用旧隔离DDL，按真实schema保留数据并完成兼容迁移。新代码生产模式允许其他业务schema共存，绝不运行原整库隔离迁移器或删除未知对象。
4. 先保存PG可恢复备份、现用POS SQLite一致性备份及现用公开菜单JSON副本；保留真实旧审批、活动SHA、价格、已售ID、订单、人员、会员数据。停掉旧目录自动写入/Excel定时同步；营业订单服务不停止。未经固定合并SHA和明确真实数据范围授权，不切换生产。用户要求的是正式生产目标，不交付隔离作为最终成果；候选测试只是上线前技术门槛。

## B. 生产模式及数据职责
- 原身份服务使用真实生产认证、HTTPS/CSRF、已核实法人及HQ grant；原 BSV_DB_A_URL 或已批准的中央identity配置维持不变。既有生产provider以C实际核准为准，当前GitHub基线要求 cloudbase_jwks、安全Cookie。
- identity与POS的环境：BSV_APP_ENV=production、BSV_CATALOG_LIVE=1；identity加 BSV_HQ_CATALOG_ENABLE=1、BSV_HQ_CATALOG_LEGAL_ENTITY_ID=真实法人、BSV_HQ_CATALOG_READ_DB_URL=原登记本机PG17只读运行角色连接、BSV_IMPORT_ROOT=身份账号私有0700根目录、BSV_CATALOG_DIR=现有私有Excel版本根目录。POS加 BSV_CATALOG_READ_SOURCE=postgres、BSV_DB_URL=原登记本机目录读连接（只在POS环境设置，不能误覆盖身份A）。POS和identity使用同一正式catalog主库。
- 生产写入角色 bsv_catalog_importer；PG owner/签名密钥仅在独立受控发布器环境，网页与POS没有写PG目录或root权限。生产worker环境另加 BSV_ALLOW_PRODUCTION_CATALOG_IMPORT=1 和原 BSV_CATALOG_ADMIN_DB_URL / BSV_CATALOG_APPROVAL_KEY_FILE；与网页服务环境分离。不能通过BSV_APP_ENV=isolated在经营库写入。
- 执行新增生产迁移 platform/lighthouse/bsv1/catalog/live_migrations/0001_sale_release.sql （已有注册原始catalog结构之后）。它只新增 catalog.sale_release、两个唯一索引及最小授权；不改原始表和历史订单。不由应用启动自动执行。核对 bsv_catalog_importer 不具备集群管理权限。
- 原始资料：catalog.active_content → C/P/M/K/R/Q/T及注册辅助字段的完整不可变版本；总部网页编辑或Excel批量审核后，原签名导入器写入真实PG、更新活动指针、审计并保留历史。真实源SHA与原文件必须相符。配方查询走PG。
- 独立销售：catalog.sale_release → 双人核准的销售快照（资料源SHA、商品ID、名称、整数分金额、内容指纹、提交与审核TR、法人及发布状态）；不是第二商品主库。现用POS SQLite只存可售投影及原交易数据；现用公开酒单JSON只存公开投影。资料变更不自动核准价格；销售申请批准后无需运营人员SSH、SQL、重启或另找AI。
- 当前既定真实POS价格政策仅C表AJ统一售价。K套餐、M采购、Q报价、P/R等资料仍可通过总部维护并入PG；K顾客既有参考展示保留，不自动成为POS成交价。不得为了声称全功能而把K参考价或Q未核准报价当实际可收款金额。若C现有正式POS已核准新的K/Q真实价格契约，合并时按该契约增量扩展，不能自行发明或破坏既有价格规则。

## C. 一次性配置工具
1. 继续使用原七表原始文件、已核验WorkBuddy包和版本归档；配置 BSV_HQ_CATALOG_SCANNER 为root安装、受审扫描器绝对路径，上传扫描必须成功，保持4MiB网关上限。按历史清单完成永久ID核对后才设置 BSV_HQ_CATALOG_ID_HISTORY_VERIFIED=1；私有 hq-catalog-drafts/verified-legacy-ids.json 内容为实际历史已用永久ID、状态HISTORY_RECONCILED及证据索引；绝不伪造。
2. 原始Excel→标准包内置转换器：services/api/bsv1/bsv_hq_workbook_package.py，使用381项登记字段及现有导入器验证。首次在私有目录使用真实基线复核行数、字段、公式、关联、辅助映射及原SHA与既有WorkBuddy规范一致；原始数据不上传Git。已审核外部转换器可选 BSV_HQ_CATALOG_CONVERTER，但不允许绕过同一包验证。
3. 网页逐项修改含公式模板时：root安装 platform/lighthouse/bsv1/catalog/recalculate-office.py 为不可由网页用户修改的可执行文件；安装现有Ubuntu仓库中LibreOffice Calc、bubblewrap，令 BSV_HQ_CATALOG_RECALCULATOR 指向该脚本，使用identity非root账号验证无网络沙箱可执行。重算仅回填缓存，必须保持原始公式签名、全部非公式输入和值及固定ID；若真实模板包含LibreOffice不兼容的公式，拒绝而非写过期缓存。保留Excel官方重算保存后上传的实际维护路径；真实模板未验收不可标记全部逐项编辑已完成。超过300处差异分批审核，受限审批字段不能普通编辑。
4. 用原授权页面给真实总部管理员申请/核准 hq.catalog.read、hq.catalog.confidential、hq.catalog.draft、hq.catalog.review、hq.catalog.release.request、hq.catalog.sale；按真实法人、HQ角色及两位自然人授权，不扩大到普通员工。提交人和审核人不可相同。真正的上架审批必须由获授权人完成，不自动从原工作簿价格推导。
5. 顾客电子酒单：将现有 menu-public.json 原样复制到已有站点的**运行数据目录**（不在Git源码树内、不在私有资料目录），设置当前Nginx/EdgeOne该资源路径指向此文件；仅该数据资源使用revalidate/no-cache或正确失效机制。保持当前网页、域名、路由、二维码不变，不覆盖站点其他文件。通过实际页面网络请求核实 URL 为 https://menu.bsvm.cn/.../menu-public.json 或 https://bsvm.cn/.../menu-public.json 的既有真实路径。若现在完全是EdgeOne静态发布，精确配置该JSON为受控Lighthouse源站资源；不能仅修改服务器一个无人读取的文件。公开文件只包含已有公开schema。确认未带员工、配方、采购字段。
6. 在root私有配置目录创建0600发布环境及政策。政策JSON字段：status=APPROVED_PRODUCTION_CATALOG；legal_entity=真实核准法人；approved_git_sha=C实际生产合并SHA；approval_ref=负责人固定SHA发布授权索引；expires_at=带时区授权有效期；draft_root=真实 identity 私有导入根目录/hq-catalog-drafts；approval_dir=root独立私有审批目录；catalog_dir=实际版本根目录；pos_database=真实POS数据库绝对路径；public_menu_json=真实顾客源站运行JSON绝对路径；public_menu_url=实际顾客网页读取的HTTPS数据地址；rollback_archives={历史来源SHA:实际私有WorkBuddy ZIP路径}。身份A连接和认证配置采用既有正式环境，不能把只读角色改成写角色。生产发布代码与Python环境必须root控制、固定实际合并SHA，无网页账号写权限。源代码与运行数据分离；若实际release为打包目录，使用同一已批准SHA的root受控Git checkout运行发布器，不启动第二套应用、不创建第二套数据库。
7. 一次安装定时发布器：
    sudo /usr/bin/python3 "$REPO/platform/lighthouse/bsv1/catalog/install-live-worker.py" --repo "$REPO" --python "$IDENTITY_VENV_PYTHON" --env "$ROOT_RELEASE_ENV" --policy "$ROOT_POLICY_JSON"
安装默认不启用，检查systemd unit使用真实路径和root私有环境。授权及实机验收完成后同命令加 --enable。每分钟消费最多一条审核申请；不监听新端口，不暴露密钥，不要求管理者每次进入服务器。原root签名器仍可执行异常恢复。开启生产前先完成首批实际营业商品接管，以免尚无中央销售批准时新单被拒绝。

## D. 真正营业工作流
1. 经营者直接访问原企业域名工作台 → 总部 → 商品与数据库（/hq/catalog）。同一员工身份。逐项编辑或上传Excel→异人审核→生成规范包（显示原始/重算差异）→申请资料生效；受控worker直接写真实PG，页面显示RAW_REVISION_ACTIVE，查询实际活动SHA。
2. 上架：同页“门店商品上下架”选择真实C商品及动作，显示当前销售状态、价格及变更提醒。首次由实际现用POS的非demo sale_enabled=1集合制作一份待审核清单，管理者逐项或批量选择明确上架/下架；不批量伪造Excel审批值。另一位获授权TR审核并确认发布。随后无需人工SQL。
3. worker核对实时权限、原始源SHA和每项指纹/整数分；原已批准商品不变时保留，若在售商品资料已改则本批必须重新批准或下架，避免静默下架或未核准改价。写PG PENDING_PROJECTION→原SQLite事务生成新的可售商品及资料镜像（历史订单快照不改）→切PG ACTIVE→确认SQLite确切可售ID和金额→更新并校验公开酒单源站→实际HTTPS读取同一sale_release_id/商品/价格，成功才回执SALE_ACTIVE。
4. 失败：在SQLite投影尚未就绪阶段不接受新价格，保留旧历史订单；已写PG批次按同一draft_id恢复，不重发不同审批。源站或CDN未同步时实际回执保持待完成，不宣称全链路成功；修复真实缓存/代理后worker继续核对。旧Excel任务即使误启动也不得覆盖已接管正式销售投影。数据恢复必须区分原始资料和销售批准，旧资料回退只移动原始活动指针；恢复销售需通过新审批重新核准对应源版本。
5. 不改变已结账/已提交订单的价格快照。现有POS草单按既有价格重核规则处理；原真实收款、转桌、出品、历史报表由C保留。

## E. 正式切换与完成标准
合并后定向运行现有 tests/bsv1/check.sh、tests/bsv1/catalog_pg17.sh、tests/identity/check.sh、现有真实浏览器营业验收。新测试覆盖实际SQLite事务、上下架、旧同步拒绝、历史订单不变、PG生产新增账本和其他schema保全。GitHub CI不等于真实主机。
一次实机闭环：①真实HQ账号进入正式HTTPS页面 ②选一款经负责人授权的正常商品，修改一个真实资料字段并由独立管理员审核，PG源SHA和对应业务行实际更新 ③新销售申请批准后PG sale_release ACTIVE、POS真实可售及正金额一致、未批准商品仍拒绝 ④电子酒单实际HTTPS显示同一商品和价格，页面读取该JSON ⑤重启后数据仍在，原历史订单/收款/人员不变 ⑥反向恢复旧资料及经批准销售版本成功。测试商品不得误公开，未经审批的营业操作不执行。上线验证可复用C已有有效证据，不反复跑无关全量流程。
在#58已核准的唯一正式发布窗口集中完成上述配置、角色、数据库迁移、代理数据路由和worker启用，不逐项等待ChatGPT提示。若真实schema/provider/公式或公开资源不兼容，只修该具体阻断，不另起项目，不伪造数据。只有真实企业网页、真实PG提交、POS销售与顾客HTTPS同步全通过，才记录 HQ_CATALOG_PRODUCTION_LIVE。否则记录准确阻断及实际完成项，不能把隔离或源码候选冒充上线。最终给经营者固定网页地址、使用路径、实际运行SHA、成功操作和可见范围。
