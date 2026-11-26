# CX-WP-H V1.4 | 收款退款与资金
This is implementation advice, not a mandatory procedure. Use actual host findings to improve it. No live code or activation.
## Route and evidence
已有正规支付渠道，微信官方API v3+支付宝获权备用，H统一支付分配/回单/账本。
Alternative: 收钱吧统一支付Web API作为收款/退款适配器；原有直连或门店正规收款保留独立备用。
收钱吧官方支付接口与退款权限说明可验证；聚合减少接口数，但不证明适用于客户H5的支付方式、自动代付或企业转售。
Adopt if: 确认实际线上场景、商户签约、支付/退款/查询及对账、授权费率、ISV许可；比较24个月费用、人工异常、独立故障域。不能提供真实代付时继续官方商家转账，不把聚合支付等同代付。
Sources: https://doc.shouqianba.com/zh-cn/ ; https://doc.shouqianba.com/zh-cn/api/sign.html ; https://doc.shouqianba.com/zh-cn/api/interface/refund.html ; https://pay.wechatpay.cn/doc/v3/merchant/4012791870
## Concrete execution recommendation
锁order allocation，已确认+在途金额≤应收；持久化DISPATCHING before I/O，未知查原单，明确不可成功终态才释放并允许客户选备用。回调验签+原商户/金额/币种核对，去重。退款锁原支付累计成功+在途≤已付。预付本金、赠送、佣金负债分别记账；七日未兑付退款权及其他法定权利不缩短。E结算锁定后H付款，未知不解锁。
## New/revised operations
- cx.payment.create.v1: order_id:id,quote_version:id,amount_minor:i,channel:s → payment_intent_id:id,attempt_id:id,state:s,launch_ref:id?; 创建allocation且在外发前持久化DISPATCHING；launch_ref经受控渠道适配器返回客户端必要参数，不能包含商户密钥
- cx.payment.status.v1: payment_intent_id:id → state:s,verified_paid_minor:i,refunded_minor:i; 原供应商确认；本人/账单权限
- cx.refund.request.v1: payment_id:id,amount_minor:i,reason:s → refund_id:id,state:s; 客户仅创建申请；授权财务批准/法定自动规则后才执行，禁止按用户输入直接退款
- cx.prepaid.balance.v1: (empty) → principal_minor:i,promo_minor:i,policy_version:id; 与佣金隔离
- cx.payout.request.v1: approved_settlement_id:id → payout_id:id,state:s; E负债锁定，H实际付款
- cx.shop.order.v1: items:items,delivery_mode:s,recipient_ref:id? → order_id:id,quote_version:id,state:s; 调用F唯一订单入口；D发权益
- cx.payment.channel.select.v1: order_id:id,client_channel:s → channels:objs,reason_codes:ss; 只列已授权可用通道；不发交易
- cx.payment.attempt.close.v1: attempt_id:id,reason:s → state:s,verified_terminal:b; 查原单并确认关单
- cx.payment.reconcile.v1: batch_ref:id → matched:i,exceptions:i; 回单匹配；异常保留
- cx.refund.status.v1: refund_id:id → state:s,refunded_minor:i; 原退款事实
- cx.payout.status.v1: payout_id:id → state:s,paid_minor:i; 本人/财务权限
- cx.prepaid.refund.v1: recharge_id:id,amount_minor:i,reason:s → refund_id:id,state:s; 法定退款审核；原渠道
- cx.shop.gift.claim.v1: claim_proof:id → entitlement_id:id,state:s; 调用D，持有人唯一
- cx.payment.webhook.accept.v1: raw_event_ref:id → accepted:b,event_id:id?; 原始回调先验签且商户绑定到租户；raw_event_ref仅服务端生成，内部注册操作不得公开通用RPC
- cx.prepaid.recharge.v1: amount_minor:i,channel:s,policy_version:id → order_id:id,payment_intent_id:id; 真实功能默认关闭；本金支付后入账
- cx.prepaid.spend.v1: order_id:id,amount_minor:i,authorization_ref:id → allocation_id:id,state:s; 分账守恒，余额锁
- cx.payout.apply.v1: liability_ids:ids,recipient_ref:id → application_id:id,state:s; 申请与实际付款权限分离
- cx.invoice.request.v1: order_id:id,invoice_profile_ref:id → application_id:id,state:s; 先人工开票，供应商引用留空
- cx.shop.fulfillment.status.v1: order_id:id → state:s,fulfillment_ref:id?; F事实投影
- cx.payment.manual.confirm.v1: order_id:id,amount_minor:i,evidence_ref:id → payment_id:id,state:s; 现有正规线下收款事实经授权核对
- cx.prepaid.history.v1: cursor:s? → entries:objs,next_cursor:s?; 本金赠送分开展示
- cx.refund.approve.v1: refund_id:id,approval_ref:id → state:s; 核对法律与金额，发起原渠道退款
- cx.payout.application.review.v1: application_id:id,approval_ref:id → state:s,settlement_id:id?; E锁定合格负债后H付款
- cx.aftersale.request.v1: order_id:id,kind:s,reason:s → case_id:id,state:s; 售后申请不自动退款
- cx.aftersale.status.v1: case_id:id → state:s,updated_at:t; 本人/授权财务或门店
## Deliverable and tests
Read FEATURE-TRACE filtered by accountable_owner and CRITICAL-CASES. Related-only entries need explicit UI/domain work, not false pass. Preserve old code when equivalent. Actual paths and schema mapping validated on host; missing binding null. Compare alternatives using observed implementation effort and recurring fee, authorization, error recovery and rollback. No claim of global best. 
## V1.3 inherited scope (historical, signatures superseded above)
# CX-WP-H｜支付、储值、付款与商城 V1.3
本文件为建议实施规格，不是代码、已上线接口或真实配置。上版V1.1/1.2历史保留；本版细化优先，现行已批准契约/源码约束优先于设计假定。执行者先对照最新主机基线及既有owner，原表/接口可复用即映射，不另建同义实体。只使用专属worktree和合成测试数据库，不直接改部署目录。局部更优方案不破坏契约可记录后采用；跨组、数据归属、资金语义变更提交ADR，由集成人一次冻结。所有外部账号/密钥/报价/门店映射未核验项保留null，绝不能猜测或写入Git。

## 数据模型（候选映射）
PaymentIntent(order,quote,total,currency); Allocation(id,intent,amount,state); Attempt(id,allocation,provider,channel,merchant_ref,revision,trade_no,state); VerifiedPayment(provider_transaction_id,amount,merchant,verified_at); Refund(id,payment,amount,state,provider_ref); LedgerEntry(account_kind,event_id,amount,sign,source); Payout(id,settlement,recipient_ref,merchant_ref,state); 礼券由D拥有、订单由F/POS拥有。

## 界面与业务动作
账单→可用渠道→用户确认→支付中/未知/完成；付款故障展示替代渠道条件。我的储值本金、赠送余额、佣金独立卡片；退款申请、商城、礼赠、发票申请。HQ对账、异常与付款审批、支付授权和限额。

## 可执行工作顺序
H-01. 真实支付优先正规现有渠道/微信JSAPI；支付宝作备用条件接入；线下人工以真实收款证据核对，不使用demo checkout
H-02. 订单金额由F报价；每个金额allocation仅一个在途attempt，锁住已支付+保留金额；未发或确认原attempt终止才能改通道，用户确认；同供应商两通道不等于独立故障域
H-03. 回调验签、商户/金额/币种/租户验证，查单确认，去重、乱序不逆转；异常双付冻结并对账退款。退款原支付渠道，累计退款≤已付
H-04. 分别记预付本金、赠送权益、佣金负债；合法退款权不可被24小时取消，实际充值默认关闭；消费时锁余额，冲正可追溯
H-05. E核准结算后H逐笔付款；用户申请与执行审批分离、税务/身份/限额、未知查原单、周期引用policy.payout；不自建现金清算
H-06. 商城以F订单、C商品、D权益；付款后幂等发券，礼赠领取引用D所有权；零售先自提；发票先申请人工处理，供应商未签留空

