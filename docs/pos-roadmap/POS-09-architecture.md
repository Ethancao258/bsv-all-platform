# POS-09｜会员、员工认领、权益与佣金 Architecture V1.0
DESIGN_READY；未部署。V2.0 POS-09；依赖 POS-07 身份授权、02/05 订单与结账、10 真实支付。核查基准 SHA 2052ef51f011be3c5898d816932d8982f420b752（BASE）；现网有效源码优先。EXISTING 为 BASE 已存在，NEW 为候选。
## 1 已有资产，禁止重写
PR #24 会员注册/偏好/员工认领；PR #26 私有网关集成。BASE 已包含：
- services/api/customer_growth/app.py，README.md。app.py 23-56 环境/数据库，103-324 模型，387-467 trusted_pos_staff_scope/staff_auth，514-603 微信/注册，604-635 顾客授权，658-760 偏好/接待，821-995 邀请/认领，996-1107 支付/佣金，1109-1157 权益预占，1159-1242 政策/纠错，1257-1319 隐私及网页。
- services/api/bsv1/bsv_growth_pos.py：install_pos_projection、make_guest_link/verify_guest_link、make_visit_context；已有一次性顾客证明120秒及只读桌次上下文90秒；不等于支付或折扣。
- services/api/bsv1/app.py:45-51 growth_integration；1236-1381 growth_customer_link、growth_visit_context、growth_staff_verify、growth_visit_verify。使用 SQLite tx()、visit_member_links.canonical_customer_id、bsv_growth_pos_consumed_nonces。
- config/data-ownership.json：customer_id/consent_id/loyalty_account_id→customer；attribution_id→marketing；TR/任职/组织→workforce；支付事件→payments；结算→operating_finance。contracts/API_AND_EVENTS.md、contracts/database/EVENTS.md。
## 2 数据源及实际模型
growth app 使用 BSV_GROWTH_ENV、隔离 BSV_GROWTH_DB_URL；生产中央 BSV_DB_URL（校验 bsv_all_prod，BASE 禁止 isolated/disabled 使用中央 URL）。从现有服务配置解析；禁止输出真实 DSN、密钥、PII。生产先核对已存在 customer owner、去重、正式迁移；candidate 表不是正式主库，禁止生产 create_all。POS 不直写会员库，仅保留稳定引用/快照。
| EXISTING ORM / 表 | 主要字段 |
|---|---|
| Customer / bsv_growth_customer_candidate；CustomerIdentity / bsv_growth_customer_identity_candidate | 公司身份候选/渠道认证 |
| CustomerTaste / bsv_customer_taste_candidate | 授权偏好 |
| ClaimTicket / bsv_marketing_claim_ticket | customer_id unique、store、expiry/status |
| Claim / bsv_marketing_claim_candidate | ticket/customer/actor_tr/policy_version/signature_version/attestation/status；PENDING_CUSTOMER/CONFIRMED 部分唯一索引 |
| Attribution / bsv_marketing_attribution_candidate | customer_id PK、actor_tr、source/status、original_supervisor_chain_json、created/confirmed_at |
| SignatureTemplate / bsv_workforce_signature_template_candidate | actor_tr+version PK、加密母版/hash；正式归 workforce |
| MembershipCycle / bsv_customer_membership_cycle_candidate | activated_by_order_id unique、customer、policy、expiry |
| Benefit / bsv_customer_benefit_candidate | cycle_id+kind unique、AVAILABLE/HELD/REDEEMED、expiry |
| BenefitReservation / bsv_customer_benefit_reservation_candidate | benefit_id PK、order_id unique、expiry/status |
| PaymentFact / bsv_growth_verified_payment_projection | order_id PK、customer/store、paid_minor/refunded_minor/paid_at |
| ProcessedEvent / bsv_growth_processed_event | event_id PK、payload_sha256 |
| Policy / bsv_marketing_commission_policy_candidate | store+version unique、base_rate_bps/full_days/reduced_days/reduced_coeff_bps/effective_at |
| Commission / bsv_operating_finance_commission_candidate | order_id PK、actor_tr、policy/rate/coeff/accrued_minor、PROVISIONAL_NOT_PAYABLE |
| CommissionLedger / bsv_operating_finance_commission_ledger_candidate | event_id PK、order_id、actor_tr、delta_minor |
| AttributionCorrection / bsv_marketing_attribution_correction_candidate | 原/拟actor、双审、证据 |
| PrivacyRequest/Audit | bsv_growth_privacy_request/bsv_growth_audit_event |
先查实际 schema 和角色；已有正式 owner 则做旧 ID 映射、双审迁移，不双写、不凭昵称合并。
## 3 EXISTING 路由
BASE_PATH=/api/v1/growth；网页 /member/、/staff/growth/、/member/privacy、/growth/health。复用 public/config、auth/wechat/start/callback、public/register、public/me、public/taste、public/pos-link；staff/me、store-options、guest-context、policy、queue、signature、signature-preview、invite、invite-qr、claims；public/claim-requests、public/claims/{claim_id}/confirm、public/marketing-preference、public/delete-request；internal/payment-event、internal/benefits/reserve；hq/commission-policy、hq/attribution-corrections、/{id}/approve。POS /api/visits/customer-link（visit_id、proof、_action_id），/api/visits/customer-context（visit_id）；内部 staff/visit verify 按现有路由。网关显式按路径分派，不被泛 /api/v1/ 截获，禁止公网访问内部接口。逐次校验 identity A、POS实际设备/班次/门店/TR及顾客授权；禁止前端自报身份；CSRF、签名、版本、重放防护。
## 4 业务规则与 NEW 候选
09.01/02 公司唯一 customer_id；首次真实到店免费注册账户，注册≠权益激活。BASE 首次核验 PAID 激活周期及 PENDING_PAYMENT attribution，隔离才自动生成样例权益。正式有效期、重激活、权益版本由经营者批准。过期不恢复旧优惠。openid 仅公众号范围；跨渠道验证与受控去重。隐私告知、同意撤回、删除请求、财务事实按规定保留并限制访问。
09.03 纸卡不作为核销权威。AVAILABLE→HELD→REDEEMED，取消/超时释放，锁 benefit/reservation，验证顾客、门店、周期、次数、订单。过期后的真实到账必须保留支付事实并转异常核对；不自动恢复退款权益。现有 order_id unique 仅支持单权益，叠加政策批准后才迁移。
09.04/05 复用员工邀请、认领、顾客确认及双审纠错。区分 原始开发者、当前服务人、组织承接人、佣金受益人；Attribution.actor_tr 单字段不够，原始归因永不无痕覆盖。
NEW 候选（已有 owner 则复用）：attribution_origin(customer_id unique,origin_tr,source_ref,confirmed_at,policy_version,original_chain_ref) 不可变；customer_assignment(customer_id,service_owner_tr,effective_from/to,version,reason) 时态唯一有效服务归属；assignment_transfer_event(from/to,requester,approver,evidence,expected_version)；beneficiary_rule_snapshot(payment allocation/order scope,policy_version,origin_tr,beneficiary_tr,employment_status,chain_version,rate_bps,coeff_bps,effective_at)。组织上下级由 workforce 管理，不重复建主档。
09.06/08/09 转交及离职：先撤销 POS 操作权；按批准政策承接客户，保留原始归因及历史已赚佣金；检查组织链无环、上级连续离职、无合格上级进入 HQ 处理。跨店按真实消费门店核价；佣金费率、年度系数、离职期及资格尚需批准，不能将 BASE 候选默认值视为政策。
09.07/10 复用 commission_for 整数分算法：round_half_up(net_minor*rate_bps*coeff_bps/100000000)，net=max(0,paid-refunded)；原代码按 first_paid_at、store policy effective_at 取阶梯。冻结受益人、适用政策、支付发生时点及费率；退款 delta=原规则重算累计-既有累计；政策更新不改历史。finance 独立审批实际应付，禁止将候选佣金自动视作工资。
## 5 与 POS-10 的关键接口
BASE payment_event 对第二次同 order_id PAID 返回409，PaymentFact.order_id PK；现有 POS 分次结账不可原样调用。NEW：按 payment_event_id/checkout_id/支付分配独立唯一；保留 order_id 聚合、provider transaction ref、实际 occurred_at/verified_at、customer/store/legal、amount_minor/currency、schema_version，退款关联原收款；现有 paid_at=now() 只是接收时间，需以核验发生时间判政策。分次到账、跨年度费率分别冻结快照；升级消费契约并保持旧单笔 v1 兼容。不得伪造新 order_id。payments owner 持权威到账，growth 只投影。未接支付仅 PROVISIONAL_NOT_PAYABLE；不可正式计佣。
## 6 交付与验收
先恢复09.01-05现有网页/API，再06-09关系/组织/政策，10冲正；可与 POS-10 合同设计并行。两员工跨店认领并发唯一；顾客证明过期/重放/跨店拒绝；重复核销仅一次；离职撤权而历史不丢；双审不同主体；原政策退款；分次支付、重复/异载荷/乱序、跨店对账；无核验支付不应付。前端仅显示授权范围，签名母版不能代替当次可靠电子签署。独立工作目录、增量迁移、语法/回归/网页验收、现有发布机制与回滚；提交实际数据源/路由/部署版本及待审批事项。