# POS-10｜支付、对账、迁移与逐店上线 Architecture V1.0
DESIGN_READY；非生产授权。V2.0 POS-10，依赖02/03/04/05经营闭环、07正式权限、09会员关联；可提前独立开发。BASE=已核查历史部署参考 SHA 2052ef51f011be3c5898d816932d8982f420b752；现网增量优先。EXISTING 已有源码，NEW 候选，先核对现网。
## 1 现有资产及数据位置
| EXISTING 源码 | 事实 |
|---|---|
| services/api/bsv1/app.py:99-125 connect/db_read/tx；176-300 DDL | BSV_DB_PATH operational SQLite；visits(id,store_id,version), orders(id,visit_id UNIQUE), order_lines(id,order_id,price_cents,quantity,checkout_id), demo_checkouts(id,visit_id,store_id,amount_cents,status TEST_SETTLED), visit_closures, audit_events, command_dedup |
| app.py:620-641 receipt | 明细、制作送达、分次及桌位历史；明确 demo_only=True/payment_verified=False |
| app.py:697-746 handle_action；887-935 submit；1016-1045 settle-demo/depart-demo | 原设备认证/幂等、分次结账与离店；演练结账不代表到账；离店检查草稿/未上桌，设 TEST_CLOSED、待清洁 |
| apps/store-console/bsv1/app.js:822-864附近 | renderHistory/renderAudit/showReceipt，原金额核对、打印/报表 |
| services/api/customer_growth/app.py:996-1107 | payment_event/commission_for；同 order_id 第二次 PAID 拒绝，候选佣金非应付 |
| config/data-ownership.json | order_id/quote_id→commerce；payment_event_id/refund_id/reconciliation_id→payments；settlement_id→operating_finance |
| contracts/API_AND_EVENTS.md；contracts/database/EVENTS.md | 机构验签/查单确认、整数分、事件不可覆盖、来源唯一 |
| config/data-contracts.json；services/api/shared/data_contracts.py::resolve_database | PG17，BSV_DB_URL，bsv_all_prod；正式迁移 owner cloudbase/migrations；兼容 BSV_DB_PATH/BSV_GROWTH_DB_URL/BSV_SOURCES_CONFIG。BASE 标记候选 PG、production_configured=false，不是全域生产迁移证据 |
| config/modules/identity-data-sources.json | A 权威授权，BSV_DB_URL/兼容 BSV_DB_A_URL；B/LOCAL 不授权 |
实际 provider、商户合同、证书、DSN、schema 和正式状态未知。从当前配置读取结构及状态，不打印密码/密钥/支付PII。先读 AGENTS.md、config/architecture-lock.json、所有权、迁移和 integrations 已有支付适配；已有 owner 则扩展。支付 owner 在批准 PG schema 单写，commerce 在迁移前仍用现有 POS SQLite 单写，growth/finance 仅投影。新增路由先注册 resolver/registry，禁止第二权威库或静默 fallback。
## 2 NEW 候选模块及逻辑表
domains/payments/、services/api/payments/、integrations/payments/、contracts/payments/pos10.openapi.json（已有同职责目录优先复用）；正式增量迁移、显式网关路径、原 POS UI 扩展。以下非现网表名。所有实体含法人/门店、UTC、currency、整数 minor、version；跨库引用由 owner 验证。
- commerce.checkout：checkout_id/order_id/visit_id/snapshot_hash/gross/discount/due_minor/state/version；checkout_line(checkout_id,line_id,quantity,price_snapshot,allocated_due)；原订单ID不变，分次预占数量不得超额，不将 demo_checkouts 改成真付款。
- payments.payment_intent：intent_id、checkout_id、merchant_account_ref、provider、merchant_request_ref(账户范围唯一)、amount_minor、currency、state、request_hash、expires_at、version；同请求同载荷复用、异载荷409。
- payments.payment_event：payment_event_id、provider/account/provider_event_id 唯一、provider_tx_id、kind、amount/currency、occurred_at/verified_at、verification_method、payload_hash、intent_ref；验签事实追加，原报文加密受控。
- payments.payment_allocation：allocation_id、payment_event_id、checkout_id/order_id、customer_id可空、allocated_minor；不超实际到账/应收，不跨错误法人门店；一订单多次收款各自分配。
- payments.refund：refund_id、original_verified_payment_ref、merchant_ref unique、requested/verified_minor、state、reason、approver、provider_ref；已退款+在途预占<=可退额；独立审批，不删除销售行。
- reconciliation_run/item：account/business_date/statement_ref/hash、交易/退款匹配、gross/fee/net/settlement_date/difference/resolution。
- inbox/outbox：event_id/source_system/source_event_id/payload_hash/schema_version/attempt/status；同事务写事实+outbox，消费幂等、异载荷隔离。
## 3 事务及状态机
CHECKOUT DRAFT→AWAITING_PAYMENT→PART_PAID→PAID（余额0）；CANCELLED需无已付或符合核验退款规则；DISPUTED需核查。INTENT CREATED→PENDING→VERIFIED_SUCCESS/VERIFIED_FAILED/EXPIRED；超时 UNKNOWN→主动查单，不重复收费。REFUND REQUESTED→APPROVED→PENDING→VERIFIED_REFUNDED/FAILED/UNKNOWN。已核验付款不被后来失败事件降级。
1. POS 服务器根据权限、订单版本、未结/预占行和成交快照核价；浏览器金额不可信。冻结 checkout 与行分配、事务内 outbox；支持分次后加单，保留原订单/桌次 ID。
2. payments 消费请求创建 intent、经持牌机构适配器发起；不在 SQLite 写锁中网络调用，不保存卡号/密码。
3. 按实际签约机构官方文档验签/证书、商户号、交易号、金额、币种和 intent；回调或主动查单核验后锁 intent，事务插入唯一 payment_event/allocation/outbox。重复同 hash 原 ACK，异 hash 隔离；内部桥签名不能替代机构核验。
4. POS 幂等消费到账投影，网络失败显示待核验，不重收费。离店要求无草稿/未送达、合法应收结清或批准的特殊处理；原清洁复位逻辑复用，不能照搬 depart-demo 自动 TEST_SETTLED。单据显示应收、已核验、退款、余额、登记方式；打印不创造支付事实。
5. 退款经审批、provider 核验后追加事件/冲正/对账；不以本地取消冒充退款。
## 4 API 与权限候选 NEW
POST /api/v1/payments/intents（checkout_id/request_id）；GET /api/v1/payments/intents/{id}；POST /api/v1/payments/refunds（原付款、金额、理由、request_id）；POST /.../refunds/{id}/approve；GET /api/v1/payments/reconciliation。对应 payments.intent.create/read、payments.refund.request/approve、payments.reconciliation.read/review 候选动作，在 identity A 正式注册；逐次核验法人/门店/岗位，CSRF、幂等，未授权默认拒绝。provider callback 单独允许列表、独立认证；具体路径/证书/签名按已签约机构文档，不编造；公网不暴露内部桥。HQ 财务权不自动来自店长。
## 5 POS-09/08/05 联动
现有 growth PaymentFact.order_id PK 只允许一次 PAID，需升级分配级事件投影；不能伪造 order_id。事件含 event_id/source_system/source_event_id/schema_version/legal/store/order/checkout/allocation/customer(如有)/currency/amount_minor/occurred_at/verified_at/correlation_id；退款关联原收款。可复用 /api/v1/growth/internal/payment-event 的签名防重结构，v1仅单笔兼容；POS-09/10共同升级v2。已到账即使权益预约过期仍保留付款事实，权益异常另处理。佣金须核验、批准政策与快照，退款按旧规则冲正，finance审批后才应付。
日报按批准营业日、门店、法人、币种：verified gross=sum verified allocated PAID；verified net=gross-sum verified REFUND；平台费、实际结算到账、应收未收、登记、现金（独立批准证据流程）、演练流水分列。provider账单逐笔匹配，差额进入异常，不自动调账。POS-08消费指标/异常，POS-05单据/CSV增加核验状态。
## 6 迁移与切换
10.06-08：只读盘点实际代码差异、配置、schema/角色、计数/唯一键/外键/历史ID映射；保护 SQLite/PG/identity/growth/供货。纳入有效现网修改到新版本，独立 worktree、加密备份、完整性检查及隔离实际恢复。候选迁移用正式 migrations；旧ID与source_system/source_event_id保留，演练不升级为真实记录。影子核对计数、逐笔金额、历史关系、增量水位、权限；客户去重需审核。
授权切换时冻结旧写入→增量同步/核对→原子切路由→确认新单写后解冻，禁止双向写。若已有新事实，回滚须先冻结、对账/受控回放，不能简单切旧库丢订单。断网仅明确未提交草稿/待核验状态，不伪造支付或绕过撤权，恢复幂等查单。
10.09-11：单店受控试用→逐店上线→GitHub与部署版本一致；保留独立地图、原动画和回滚机制。
## 7 执行及验收
10.01-05先隔离 adapter、订单/支付关联、回调、退款、对账；10.06-11归档/迁移/恢复/单店/逐店/版本同步。测试分次付款、重复/乱序/异金额/商户、部分退款、超时查单、断网重放、过期权益、佣金冲正、账单差额、异店越权；浏览器实际验收。真实渠道选择、商户签约、官方规范和监管/隐私要求、生产密钥、资金、正式数据迁移及生产切换需经营者明确授权；未批准可继续隔离研发，不允许测试 success 变真收款。交付实际 schema/API/测试证据/部署 SHA/备份恢复/未通过项。