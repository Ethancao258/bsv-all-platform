# CX-WP-G V1.4 | 第三方核销
This is implementation advice, not a mandatory procedure. Use actual host findings to improve it. No live code or activation.
## Route and evidence
收钱吧智慧经营聚合核销；人工官方端作为低风险备用。
Alternative: 美团官方顾客点餐自助核销 + 抖音官方券准备/核销/券状态查询两适配器。
直接获得平台原生能力及独立退出路径；美团明确支持品牌小程序自助验券，抖音查询接口要求验券准备返回的encrypted_code，不能用明文替代。
Adopt if: 聚合未获消费者自主核销或ISV授权、报价/异常恢复不合格，而平台直连实测可用；或业务量使维护净成本更低。若两边未授权，人工官方核销，不模拟真实成功。
Sources: https://doc.shouqianba.com/docs-for-smart/ ; https://developer.meituan.com/isv/daocan/ ; https://developer.open-douyin.com/docs/resource/zh-CN/local-life/develop/OpenAPI/general-capabilities/life.capacity.fulfilment/certificate.get ; https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/open-capacity/solutions/life-service-solutions/verification-tool
## Concrete execution recommendation
先查券/确认平台、门店、SKU与份数→持久化consume attempt和原binding/requestId→发送→原单查询→确认核销事实→F幂等补单。撤销必须针对具体consume_attempt，成功+在途撤销数量不得超已核销。业务状态与POS履约状态分开；H结算到账才算收入。
## New/revised operations
- cx.coupon.query.v1: platform:s,coupon_code:s,store_id:id → intent_id:id,offer:obj,query_expires_at:t,available_count:i; 虽不核销，但创建短期查券intent，限频、幂等、加密；门店/主体绑定
- cx.coupon.consume.v1: intent_id:id,visit_id:id,count:i,confirmed_offer_version:id → state:s,external_fact_id:id?,order_id:id?; 平台成功与POS接单分开
- cx.coupon.status.v1: intent_id:id → consume_state:s,fulfillment_state:s,consumed_count:i,cancelled_count:i; 结果原渠道查询
- cx.coupon.cancel.v1: consume_attempt_id:id,count:i,reason:s → cancel_id:id,state:s,cancelled_count:i; 仅针对原核销流水；部分撤销累计成功+在途≤已核销；旧intent需映射到明确attempt，不允许猜测
- cx.coupon.manual.record.v1: visit_id:id,platform:s,external_evidence_ref:id,items_snapshot:items → external_fact_id:id,state:s; 官方端证据，不能自报核销成功
- cx.coupon.reconcile.v1: batch_ref:id → matched:i,exceptions:i; 查核销/撤销/POS/结算；不直接改款
- cx.coupon.history.v1: cursor:s? → redemptions:objs,next_cursor:s?; 本人或授权门店，券码脱敏
## Deliverable and tests
Read FEATURE-TRACE filtered by accountable_owner and CRITICAL-CASES. Related-only entries need explicit UI/domain work, not false pass. Preserve old code when equivalent. Actual paths and schema mapping validated on host; missing binding null. Compare alternatives using observed implementation effort and recurring fee, authorization, error recovery and rollback. No claim of global best. 
## V1.3 inherited scope (historical, signatures superseded above)
# CX-WP-G｜第三方核销 V1.3
本文件为建议实施规格，不是代码、已上线接口或真实配置。上版V1.1/1.2历史保留；本版细化优先，现行已批准契约/源码约束优先于设计假定。执行者先对照最新主机基线及既有owner，原表/接口可复用即映射，不另建同义实体。只使用专属worktree和合成测试数据库，不直接改部署目录。局部更优方案不破坏契约可记录后采用；跨组、数据归属、资金语义变更提交ADR，由集成人一次冻结。所有外部账号/密钥/报价/门店映射未核验项保留null，绝不能猜测或写入Git。

## 数据模型（候选映射）
CouponIntent(id,tenant,store,platform,code_ref,query_version,expires_at,offer_mapping_version); ConsumeAttempt(id,intent,provider_binding,request_id,count,state,sqb_order_id?,external_order_ref?); ExternalFact(id,platform,store,provider_fact_ref,count,state); CancelAttempt(id,consume_ref,request_id,count,success_count,failed_count,state); FulfillmentLink(external_fact_id,order_id,state). 供应商返回的码短期加密，日志仅掩码。

## 界面与业务动作
客人选择美团/抖音→输入券码→查券显示套餐及可核数量→选择份数与确认→核销处理中/成功待接单/已接单。员工可见未决、补单、部分撤销、人工官方验券证据；HQ对账。

## 可执行工作顺序
G-01. 确认收钱吧ISV、逐店授权与报价；美团应用仍需品牌接入；没授权先人工官方端及合成adapter
G-02. 优先manual/query与manual/consume，显式platform；保存门店映射、offer及SKU版本；请求count，遵守供应商允许范围；代金券和套餐分别处理，不从名字模糊匹配SKU
G-03. 发送前持久化intent/requestId/绑定；查询过期重新查券并确认；未知结果按原requestId与原门店调用consume/result，不自动重发或更换供应商
G-04. 成功保存sqbOrderId、外部订单及核销份数；事务outbox补建POS唯一履约；分次核销保留每次事实，不以券码作为唯一消费ID
G-05. 撤销用原sqbOrderId+独立requestId+count，记录部分成功/失败与累计量；仅成功份数可调整履约，已出品人工处理；cancel/result核对未知结果
G-06. 每日匹配平台核销/撤销、POS履约、H净结算；人工兜底必须记录可信官方证据，不能把手工标记当平台回调

