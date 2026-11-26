# CX-WP-H｜支付资金商城
共同研发建议，不是强制步骤；MUST见ARCHITECTURE；局部等效优化可直接采用。初始只读START-HERE、本文件及公共ARCHITECTURE；按需查INDEX，不重复读历史。
## Route and evidence
已有正规支付渠道，微信官方API v3+支付宝获权备用，H统一支付分配/回单/账本。
Alternative: 收钱吧统一支付Web API作为收款/退款适配器；原有直连或门店正规收款保留独立备用。
收钱吧官方支付接口与退款权限说明可验证；聚合减少接口数，但不证明适用于客户H5的支付方式、自动代付或企业转售。
Adopt if: 确认实际线上场景、商户签约、支付/退款/查询及对账、授权费率、ISV许可；比较24个月费用、人工异常、独立故障域。不能提供真实代付时继续官方商家转账，不把聚合支付等同代付。
Sources: https://doc.shouqianba.com/zh-cn/ ; https://doc.shouqianba.com/zh-cn/api/sign.html ; https://doc.shouqianba.com/zh-cn/api/interface/refund.html ; https://pay.wechatpay.cn/doc/v3/merchant/4012791870
## Concrete execution recommendation
锁order allocation，已确认+在途金额≤应收；持久化DISPATCHING before I/O，未知查原单，明确不可成功终态才释放并允许客户选备用。回调验签+原商户/金额/币种核对，去重。退款锁原支付累计成功+在途≤已付。预付本金、赠送、佣金负债分别记账；七日未兑付退款权及其他法定权利不缩短。E结算锁定后H付款，未知不解锁。

## 最小可交付切片
锁allocation→原通道DISPATCHING→验签查单→真实事实→原渠道退款→账本对账；E负债锁后付款，商城复用F/D。
## 真实复用证据（历史SHA，运行态未知）
services/api/customer_growth/app.py:237–246,1045–1115 PaymentFact /internal/payment-event — reuse verified fact contract only; real payment adapter UNKNOWN
## 所属代码及业务对象
现有integrations/payment及资金模块；F订单、D非现金资产、E应付归因

PaymentIntent(order,quote,total,currency); Allocation(id,intent,amount,state); Attempt(id,allocation,provider,channel,merchant_ref,revision,trade_no,state); VerifiedPayment(provider_transaction_id,amount,merchant,verified_at); Refund(id,payment,amount,state,provider_ref); LedgerEntry(account_kind,event_id,amount,sign,source); Payout(id,settlement,recipient_ref,merchant_ref,state); 礼券由D拥有、订单由F/POS拥有。

## 界面与业务动作
账单→可用渠道→用户确认→支付中/未知/完成；付款故障展示替代渠道条件。我的储值本金、赠送余额、佣金独立卡片；退款申请、商城、礼赠、发票申请。HQ对账、异常与付款审批、支付授权和限额。


## 界面与验收
页面：H-CHECKOUT、H-HISTORY、H-BALANCE、H-SHOP、H-HQ。复用三端壳，UI/PAGES与DESIGN按需查；本组36项功能按accountable_owner过滤FEATURE-TRACE，操作按owner查INDEX，必要时与delivery_owner合作；schema使用唯一CONTRACTS文件，不逐个创建HTTP。按合成FIXTURES/CASES测试，真实配置留空，外部授权未取得不假装可用。对真实运行路径不明项先只读核实。
## 可直接复制的启动指令
领取CX-WP-H。从总集成人确认的共同开发基线及独立worktree读取START-HERE、ARCHITECTURE、本任务书。选择现有代码复用、首选、备选或更短等效路径，记录证据；按最小切片实现和测试。只改本组文件；共享文件、迁移及POS由真实owner协调。未获授权标BLOCKED_LIVE，使用合成fixture继续开发；不改运行目录、不未经审批部署。交付SHA、功能ID、测试证据、阻断与回退。局部优化无需反复申请。