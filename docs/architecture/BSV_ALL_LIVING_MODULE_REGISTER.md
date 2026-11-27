# BSV ALL｜全程序架构与持续需求总清单 V1.0
2026-11-27 | 架构治理候选 | 非运行配置，不授权研发/发布 | 维护入口：本文件
依据：main e2a0368bb89d30627c5eae9be062cae38f82760d（治理）；feature/bsv1-excel-catalog 2052ef51f011be3c5898d816932d8982f420b752（已读取代码树、路由注册及数据契约）；planning/next-deliveries-20261126 88e9895ffcd24bc42b441aca039e7b4f0a01cca9（PR #57 路线）；#44/#58 接管；#52 既有供货执行卡、#59 需求设计。
**禁止把任何分支、CI、设计清单等同线上事实。** 实际运行 SHA/DB schema/可用路由仍由 C 实机核实。仅展示脱敏逻辑信息，无真实数据/连接参数。

## 快速入口｜固定架构 + 动态标注 + 执行工单（CHANGE-OVERLAY-V1）
**[固定五年架构（不可变SHA）](https://github.com/Ethancao258/bsv-all-platform/blob/6c64056f2d96f545a346ad94c169d53e502b3f14/docs/architecture/five-year-foundation/BSV_ALL_2026_2031_ENTERPRISE_ARCHITECTURE_FOUNDATION.md)**：日常开发不改架构正文、不复制全套架构。本文件是其动态变更标注层，唯一维护入口；原固定SHA不会显示后续活动状态，必须同时读取[本动态清单最新版本](https://github.com/Ethancao258/bsv-all-platform/blob/docs/living-architecture-register-v1/docs/architecture/BSV_ALL_LIVING_MODULE_REGISTER.md)（当前候选分支，若合并并迁移至main，由架构负责人更新入口）。

每项需求仅维护两个业务记录：①本文件受影响模块的简短括号及议案索引；②唯一执行Issue的任务规格、进展和验收。业务代码/测试仍按正常PR修改。研究阶段不写生产。新议案用稳定proposal_id；工单号不重用，阶段后缀如 SUP-59/P1 不是新项目。议案决策状态在本文件历史表唯一维护；执行状态以对应Issue为准，模块括号不重复状态而是引用该行。已否决/延期移除活动括号或按需恢复；已发布移除活动括号，更新已验收能力与证据，保留历史。只有改变冻结原则或权威所有权才需要ADR及新版固定架构，常规功能变更不改原文。

当前首个应用：**[SUP-59 / NEXT-SUPPLY01](https://github.com/Ethancao258/bsv-all-platform/issues/52)**，决策状态 PROPOSED，研发准备已登记，现阶段仅设计；#44/#58 发布门禁未解除，未授权编程或部署。模块栏内的 SUP-59 均表示同一议案，不是16个不同项目。具体要求与阶段见执行卡 #52；#59为历史需求设计来源。旧设计中 container_id 是逻辑描述，必须优先复用已核实 package_id，不另造重号；配送签收不复用采购 receipt_id 主键。

## 0. 这份清单如何维护
唯一用途：跨对话汇总业务功能与候选变更，按模块追踪。不是第二份数据所有权、代码路由、迁移或发布注册表。以 config/data-ownership.json、config/change-routing.json（集成分支）、config/data-contracts.json、config/app-registry.json、config/use-case-registry.json 及 contracts/ 为技术权威；本表的路径为参考代码树实见或注明候选。出现分歧先核实，不能为了匹配本表修改生产。
每次新需求先读取 main 本文件（未合并时读最新获准 PR 分支）、相关现有执行卡和真实代码；列出 PRIMARY（负责实现）、ADAPTER（需要改契约/适配）、READ（只读依赖）、EVENT（发布/订阅）、NO_CHANGE（明确不改）；标明数据 owner、读/写权限、既有 ID、现有端点、必要新增、回归/停止点。先登记议案 ID，再在受影响模块行末写（+议案ID:功能），不复制业务规格。议案状态单处维护：PROPOSED→APPROVED→READY→IMPLEMENTING→STAGED_VERIFIED→RELEASED；也可 DEFERRED/REJECTED/SUPERSEDED/BLOCKED。批准方案不等于批准开工/生产。
若否决：改状态 REJECTED 并记录日期/决策者/原因，删除活动模块行的该议案括号；保留议案历史与 Git 记录，不删已上线功能或实际数据。若已实现再撤销，另立回退议案。被替代方案用 supersedes。分支并发采用最新 blob SHA 更新和冲突复核，禁止覆盖其他议案；每次只改本议案相关行，PR/CI 后合并。更新状态必须附证据；未知写 UNKNOWN。公开文档不得放经营明细、凭证、私人资料。新模块技术ID只有经注册表审核才生效；下表 M 编号仅是阅读索引。

## 1. 入口及圈层
BSV ALL=共享底座，非第四圈层。BSV1基础经营、BSV2增强增长与中央供货（沿用现有注册 bsv2.central_supply）、BSV3资本。门店基础收货/库存属于 bsv1.local_procurement_inventory；是否改行政归属另立ADR，不影响数据owner。
六个入口：apps/hq-console（总部）、apps/staff-center（员工/学院）、apps/store-console（门店/POS）、apps/guest-web（顾客）、apps/inspector-console（督查）、apps/partner-portal（合作）。入口不是独立数据库。
四类参考后端：services/api/identity、bsv1、supply、customer_growth；共享鉴权、网关、通知、同步与发布设施。不得因为新增功能就新增进程或根目录。保持现有14根目录。

## 2. 程序功能总清单（活动议案括号可删；基线不能无故删除）
状态：CODE=参考分支有对应代码/契约，非实机证明；DESIGN=设计或预建卡，尚无可用证明；MIXED=已有部分代码、关键缺口待核；UNKNOWN=运行状态未知。所有行实际线上状态 UNKNOWN，除非 C 提供实机证据更新。M01-M25是本文件阅读编号，不是注册表ID。
|编号|程序/模块（既有路由ID如有）|已有参考位置/能力|数据owner与事实|状态/现有工单|活动议案|
|---|---|---|---|---|---|
|M01|统一身份与权限 identity-api / identity-hq-ui|services/api/identity; apps/hq-console/identity; apps/staff-center/identity；人员与授权|identity_access: auth_subject_id/grant_id；workforce: employee_id|CODE #47|（+[SUP-59](https://github.com/Ethancao258/bsv-all-platform/issues/52)：制作/发货/收货/处置动作级鉴权）|
|M02|组织门店与库位|config/data-ownership.json; supply.C; 门店映射契约|organization: store_id/legal_entity_id/org_unit_id|MIXED #47|（+[SUP-59](https://github.com/Ethancao258/bsv-all-platform/issues/52)：来源/目的/库位合法映射）|
|M03|文森特学院 vincent-academy|services/api/identity/academy_api.py; academy_policy.py; apps/staff-center/identity|learning: course_id/credential_id；catalog: SOP引用|CODE #47|（+[SUP-59](https://github.com/Ethancao258/bsv-all-platform/issues/52)：生产/验收资格及新品指引引用）|
|M04|排班、考勤与交接 store-shifts|services/api/identity; domains/workforce; 员工中心；排班已有隔离契约，考勤事件待核|workforce: shift_id/employee_id/employment_id|MIXED #47|（+[SUP-59](https://github.com/Ethancao258/bsv-all-platform/issues/52)：上下班事件触发门店任务）|
|M05|总部商品、物料、配方与导入 reviewed-import|services/api/bsv1/bsv_catalog_*; config/data-contracts.json; PR40/42/39|catalog: product_id/material_id/recipe_version/publication_id|CODE/MIXED #50|（+[SUP-59](https://github.com/Ethancao258/bsv-all-platform/issues/52)：批准效期、开封规则、储运、标准装量、SOP版本）|
|M06|POS点单/桌台/人工收款 store-pos|services/api/bsv1/app.py; apps/store-console/bsv1; bsv_layouts.py|commerce: order_id；payments: payment_event_id（真实到账另核）|CODE #44/#58|（+[SUP-59](https://github.com/Ethancao258/bsv-all-platform/issues/52)：后续批准配方耗用与禁用物料提示；不改支付）|
|M07|调酒辅助与出品|services/api/bsv1; catalog配方接口|catalog: recipe_version；service_ops: service_event_id|MIXED #45|（+[SUP-59](https://github.com/Ethancao258/bsv-all-platform/issues/52)：可用批次/新品用法；后期耗用事件）|
|M08|总部地图/设备POS|services/api/bsv1/bsv_layouts.py; bsv_device_pos.py; apps/hq-console/bsv1|organization: store_id；identity_access: device_id/grant_id|CODE #38|无|
|M09|顾客电子菜单 guest-menu|apps/guest-web/bsv1; public_menu_projection.py|catalog: publication_id；只读公开投影|CODE #51|无|
|M10|顾客扫码点单/核券|apps/guest-web; commerce/市场平台契约|commerce: order_id；payments 外部确认|MIXED #51|无|
|M11|会员/客户/认领 customer-growth|services/api/customer_growth; apps/guest-web/member; apps/staff-center/growth; bsv_growth_pos.py|customer: customer_id/consent_id；marketing: attribution_id|CODE #48|无|
|M12|佣金/会员权益|customer_growth；营销/财务契约|customer: loyalty_account_id；marketing: attribution_id；operating_finance: settlement_id|MIXED #48|无|
|M13|中央供货 supply-api|services/api/supply; apps/hq-console/supply; apps/store-console/supply; contracts/supply；配送/签收/补货预览|production: batch_id/shipment_id/label_id|CODE，D权威事务未证实 #52|（+[SUP-59](https://github.com/Ethancao258/bsv-all-platform/issues/52)：计划→生产→逐瓶分装→配送→验收→A4）|
|M14|采购/库存/盘点（复用 supply-api）|services/api/supply; contracts/supply；库存/五档观察|procurement: supplier_id/purchase_order_id/receipt_id；inventory: stock_lot_id/stock_movement_id/inventory_count_id|MIXED #52|（+[SUP-59](https://github.com/Ethancao258/bsv-all-platform/issues/52)：FEFO、逐批剩余、隔离、实际报损、追溯）|
|M15|标签设备 device-label|integrations/devices；现有设计/模板需从受控交付核查|production: label_id/batch_id；容器复用package_id（owner待注册确认）|DESIGN #52|（+[SUP-59](https://github.com/Ethancao258/bsv-all-platform/issues/52)：实际装量、死期、同件重印、物理验收）|
|M16|督查 quality-inspection|services/api/supply; apps/inspector-console; contracts/supply|quality: inspection_id/finding_id/corrective_action_id|CODE，E权威写入未证实 #53|（+[SUP-59](https://github.com/Ethancao258/bsv-all-platform/issues/52)：冷链异常、效期违规、召回及复核）|
|M17|工作台/公告/任务/日会|apps/staff-center/identity/workbench.*; #46; service_ops域|service_ops: task_id/incident_id；knowledge: acknowledgement_id|MIXED #46|（+[SUP-59](https://github.com/Ethancao258/bsv-all-platform/issues/52)：上班任务、到货准备、报损、下班交接）|
|M18|知识库/SOP/培训材料|domains/knowledge; 学院及商品SOP已有部分资料|knowledge: document_id/version；catalog: recipe_version|MIXED #45/#47|（+[SUP-59](https://github.com/Ethancao258/bsv-all-platform/issues/52)：新品使用说明版本化与展示）|
|M19|支付/退款/对账|domains/payments; integrations/payment; POS人工登记|payments: payment_event_id/refund_id/reconciliation_id|MIXED #49|无|
|M20|经营财务/薪资/SDF|domains/operating_finance; POS日报；#54|operating_finance: cost_entry_id/payroll_run_id/settlement_id|MIXED #54|（+[SUP-59](https://github.com/Ethancao258/bsv-all-platform/issues/52)：只读实际损耗和采购成本供核算）|
|M21|合同/人事档案/离职|workforce/knowledge/compliance；#56|workforce: employment_id；knowledge: document_id|DESIGN #56|无|
|M22|客诉与回访|customer_growth; quality; #53|customer/quality/service_ops|MIXED #53|无|
|M23|外部合作与推广/商业化|apps/partner-portal; capabilities/bsv2; domains/partnership/marketing|partnership: partner_id/agreement_id/project_id；marketing: campaign_id|DESIGN|无|
|M24|资本治理/合规|domains/capital/compliance; capabilities/bsv3|capital: capital_decision_id/funding_id/investment_id；compliance: license_id/policy_id|DESIGN|（+[SUP-59](https://github.com/Ethancao258/bsv-all-platform/issues/52)：仅合规资格读取；资本不变）|
|M25|集成底座：部署、同步、事件、AI、硬件、备份 deployment-config|platform/lighthouse; integrations/vision/supply_photo.py; integrations/ai/messaging; services/api/shared; config/change-routing.json|event_audit: audit_event_id/sync_event_id；原owner不变|MIXED #55|（+[SUP-59](https://github.com/Ethancao258/bsv-all-platform/issues/52)：G通知/outbox、F识别候选、只读备份、适配及发布）|

## 3. SUP-59 议案关联矩阵（初始设计快照；#52唯一执行卡）
设计详见 #59；#52 既有供货执行卡扩展需求，不开新项目、不开新服务、不重复建供货库。#44/#58 当前发布优先；#50产品批准、#47身份/班次契约以及#46任务契约按实际依赖满足后才启用对应阶段。
|模块|角色|读取/写入边界|接口与实现计划|
|---|---|---|---|
|M13供货|PRIMARY|写生产计划、批次、标签、配送事实；D是中央事务唯一写口|复用 supply/main.py、gateway.py、domain.py、shipment_contract.py；原 /api/shipments、prepare/dispatch/receive、/api/reorder/preview；新增批次、分装、A4生成须先查实机|
|M14库存|PRIMARY|D原子写库存流水，不能写商品或人员主档|复用 /api/inventory、/api/stock-count；观察盘点不能直接调账；逐件效期、隔离、报损补充正式事务|
|M05商品|ADAPTER|A只读已批准物料、配方及效期；维护审批仅catalog写|参考 /api/v1/catalog/products 及 P/M域查询、A /items；保留固定ID，SKU/短码不是主键；补齐审批规则并做版本快照|
|M01身份/M02组织|READ|B逐次核权；C读取组织门店库位|现有 B /auth/me、C /stores；真实中央仓ID由组织批准；禁用DEMO|
|M03学院/M18知识|READ/ADAPTER|读取资格/批准SOP；不复制课程与配方|复用 Academy 资格及知识版本；门店新品卡按现有权限显示|
|M15标签|ADAPTER|读A及D；D记录标签/同件重印事实|现有HPRT模板优先，先验证真实设备；二维码引用package_id，不额外发容器主码|
|M04排班/M17任务|EVENT/ADAPTER|workforce唯一考勤；service_ops唯一任务|消费已确认开/闭班事件，生成门店任务；考勤不能被任务结果覆盖；若尚无真实事件先用工作台手动加载，不能假打卡|
|M16督查|EVENT/ADAPTER|E保有独立核查/整改事件|现有 inspections/review；隔离/召回通过D，督查不直接冲库存|
|M06 POS/M07出品|READ/EVENT 后续|读取确认出品与批准耗用；D唯一扣减|优先出品事件，不把支付重复当耗用；未具备批次分配时不可虚构逐批扣减；第一阶段可实盘|
|M20财务|READ 后续|读取D、采购、成本版本，不在供货写财务总账|损耗、原料成本汇总投影；不估算替代实际账|
|M24合规|READ|读取已有许可及安全要求|实际生产/储运资格、已批准规则核验；不新增资本逻辑|
|M25底座|ADAPTER|F候选、G通知，事件审计独立；配置注入|/api/photo-preview 已存在；外部AI仅草稿；G真实发送器待核；事务outbox、幂等与权限|
|M08-12、M19、M21-23|NO_CHANGE|不改地图、菜单、会员、支付、合同、客诉或合作主逻辑|仅在另有明确需求时单独议案|

## 4. 数据库物理/逻辑接法
参考 config/data-contracts.json / config/modules/supply-sources.example.json / contracts/supply/HANDOFF.md。逻辑A-G不等于七个新数据库，也不等于七个真实已接通服务。参考分支A/C/D/E尚未接通权威源，B隔离只读，F/G可选。当前真实数据库与运行态必须实机确认。
|源|唯一owner/作用|SUP-59操作|
|---|---|---|
|supply.A|catalog产品物料批准主档；参考PG catalog及版本导入|只读固定ID和已批准效期/SOP，导入不等于批准；禁止供货端写主档|
|supply.B|identity_access/workforce身份权限|服务端逐次核权；不可用时拒绝正式事务|
|supply.C|organization门店与库位|只读，使用现有门店ID和合法仓库映射|
|supply.D|production/inventory/procurement事实|单一权威事务：计划/批次/包装、发货在途、验收及库存流水；使用request_id+expected_version；禁止demo SQLite成为正式账|
|supply.E|quality独立督查|独立授权写异常/复核；不覆盖D|
|supply.F|vision候选|图片/自然语言候选，不直接过账|
|supply.G|event_audit通知/outbox消费者|订阅真实事件；通知失败不改库存结果|
身份隔离PG、业务PG17候选、POS SQLite经营账本/商品投影、供货demo/cache、客户增长存储的权威边界不得混淆；缓存仅限已批准只读资料/待同步命令。物理主库是否CloudBase或Lighthouse以真实已批准部署为准，绝不借本议案迁库。业务库的receipt_id现属procurement，配送签收必须复用 shipment_id + 已有签收子记录；新增标识应先经过owner审核，避免同名receipt_id双主。现有lot_id→batch_id、package_id→容器、item_id→固定产品键需要 crosswalk，不造 container_id 重复主码。计划与标签/库存关系先核实已有schema。
数据链：catalog批准规则→production批次快照→包装/标签→D调拨发货/签收原子流水→inventory余额/效期→service_ops任务→实际处置D流水→财务只读汇总。UTC存储，北京时间展示；禁用时刻不因打印、调拨重置，使用最早有效期限。A4到货与死期表从同一已确认事实投影，后者包含旧库存；过期先隔离，物理销毁须人工确认。禁止缺效期/许可直接正式放行。

## 5. 议案历史（单一状态来源）
|议案ID|状态|执行归属|活动模块|决策/原因|
|---|---|---|---|---|
|SUP-59|PROPOSED|[#52 执行](https://github.com/Ethancao258/bsv-all-platform/issues/52)；[#59 需求](https://github.com/Ethancao258/bsv-all-platform/issues/59)|M01-07（除无关支付）、M13-18、M20、M24-25|2026-11-27：提出中央供货闭环；待确认实机基线及总控批准，暂不启动；无生产授权|
新议案需使用同样格式，细节独立Issue，状态仅在本行维护。被否决/延期不隐藏历史。清单所有实际运行状态由 C/后续发布者提供真实 SHA、验收证据后更新，未经实机不得填 RELEASED。

## 6. 初始实现与验收摘要（详细实施以#52为准）
P0 先 #58 完成/冻结；核对真实服务树、D/E及catalog schema和已存在代码，确认唯一写入owner；将 #59 扩展并入 #52，不改 #44 当前范围。
P1 catalog效期批准契约、批次/分装及原标签；P2 既有配送签收真实事务、旧历史保留、A4两份；P3 任务/考勤订阅、效期处置、召回；P4 可选POS消耗、预测及AI草稿。P1/P2受许可/效期批准与真实D事务前提限制。P3依赖#46/#47有效任务和考勤契约；未完成不能伪称自动联动。禁止同时多Agent写共享文件/生产库。
验收：三店合成分装、450+350mL、10发9收、并发/幂等、跨店拒绝、时间边界、重印、纸质旧版替换、缺规则拒绝、断网不假成功、旧功能回归。先实机隔离网页和打印验证，后授权试点。停点：交付唯一SHA、PR、迁移/回退、验证结果和阻断；未经批准不切生产。业务功能研发必须先登记此表，新增数据域/主键/接口只经权威注册表审核。
