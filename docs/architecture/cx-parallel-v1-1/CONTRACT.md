# CX统一契约与供应商注册规范（候选冻结 v1）
不新增第二权威源；现有键类型由真实schema决定。跨域只经受控API/事件。每项操作注册 operation_id（见 registry），内部调用通过适配器/受控服务，而非运行时任意URL或从GitHub加载代码。语义版本 v1，新增可选字段兼容，破坏性变更新版本。
## 请求/结果
请求信封：contract_version, request_id, idempotency_key（写入必需）, operation_id, tenant_id（服务端可信上下文生成）, legal_entity_id, store_id（适用时）, actor_type, actor_id（认证派生）, correlation_id, occurred_at_utc, payload。主体、权限、租户、价格、支付状态均不可由浏览器自报。ID保持原类型，金额整数分+币种，数量整数最小单位或精确decimal+unit，时间UTC。响应：request_id, status(OK/REJECTED/PENDING/UNKNOWN), error_code, data, retryable, correlation_id。建议错误：AUTH_REQUIRED/FORBIDDEN/TENANT_MISMATCH/NOT_FOUND/INVALID_ARGUMENT/CONFLICT/IDEMPOTENCY_CONFLICT/UNAVAILABLE/RESULT_UNKNOWN/FEATURE_DISABLED/NOT_ELIGIBLE。HTTP 401/403/404/409/422/503按实际框架。异步请求返回202待处理，不代表履约/付款成功。
幂等键唯一范围 tenant+operation+actor+key，保存规范化请求hash与最终结果；同键异参拒绝；并发唯一约束，未知状态查原记录；跨服务使用现有事务+outbox/inbox去重，禁止伪分布式事务。
## 关键操作最小语义（字段名称为合同提案，现有同义字段须映射）
- catalog.public(store_id,publication_id?) -> published_version, products[{product_id, price_minor,currency,public_tags,availability}], only public projection.
- customer.me() -> customer_id, member_status, eligible_entitlements summaries; private only.
- visit.join(store_id,seat_locator,join_proof) -> visit_id, scoped short-lived access; POS is owner.
- order.submit(visit_id,items[{product_id,quantity,options}],quote_version) -> order_id,status, price snapshot; F writes via POS owner.
- coupon.query(platform,code,store_id) -> intent_id, offer snapshot, eligibility; consume(intent_id,visit_id,confirmed_offer_version) -> pending/success/unknown, external_fact_id; cancel/status use original intent. Codes masked in logs.
- order.external_fulfill(visit_id,external_fact_id,items_snapshot) -> single order_id, fulfillment_status; unique tenant+external_fact_id; only trusted G.
- entitlement.reserve(entitlement_id,visit_id,quantity,quote_id) -> reservation_id; consume(reservation_id,fulfillment_ref); release(reservation_id) after verified non-fulfillment.
- payment.create(order_id,quote_version) -> payment_intent_id, provider client package; status(payment_intent_id) -> verified state; refund.request(payment_id,amount_minor,reason) -> refund_id,status. No trust client callback.
- commission.accrue(verified_payment_event_id,fulfillment_ref) -> immutable accrual; reverse(refund_id) -> adjustment; eligible(beneficiary_id) -> approved liability references; payout.request(approved_settlement_id) -> payout_id,status. No double pay.
- custody.adjust(custody_id,quantity,unit,action,staff_authority,reason) -> ledger entry, balance; timer.status(service_session_id) -> start,end,server_now,state.
- booking.request(resource_id,time_range,party_size) -> booking_id,pending; service.request(visit_id,kind,details) -> task_id,state.
- auth.login(provider,provider_proof) -> scoped session; customer.bind(proofA,proofB) -> verified binding; age() stores declaration and independent verification result.
## Event envelope
event_id,event_type,event_version,tenant_id,legal_entity_id,store_id,aggregate_type,aggregate_id,occurred_at_utc,producer,correlation_id,causation_id,payload. Types (proposal, reuse existing equivalent): cx.order.fulfilled.v1, cx.payment.verified.v1, cx.refund.verified.v1, cx.coupon.consumed.v1, cx.entitlement.changed.v1, cx.commission.eligible.v1. Only owning service publishes; signature/service identity verified. No full PII; idempotent inbox.
## Runtime provider binding
Registered capability and operation ID -> tenant/environment binding -> adapter_id/version -> endpoint_ref + credential_ref + merchant/store mapping + allowed operations + policy/config revision. Runtime configuration managed by existing protected server configuration or scoped database registry; bootstrap mapping remains protected outside DB to avoid circular dependency. Never save actual secrets in registry. No arbitrary URL input to backend; allow-listed HTTPS providers, DNS/TLS validation, egress restriction, no private addresses or redirects unless explicitly approved private internal route; protocol/schema/timeout/retry tests. Read-only approved static fallback only. Financial operations pin original provider, merchant, config revision and external IDs. Config changes have candidate/validated/approved/active/retired states, audit and rollback; a new protocol requires adapter implementation, not simply changing URL. No hot download/execution of code.
## Proposed operations/data ownership
Use registry mappings; any new IDs or schema proposals reviewed by single integrator under existing owner registries. Runtime flags default closed and depend on tenant + store + permission, not client choice. No multi-tenant exposure until isolation/backup/authorization validated.
