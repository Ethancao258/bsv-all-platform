# CX-WP-E｜推荐归因及佣金 V1.3
本文件为建议实施规格，不是代码、已上线接口或真实配置。上版V1.1/1.2历史保留；本版细化优先，现行已批准契约/源码约束优先于设计假定。执行者先对照最新主机基线及既有owner，原表/接口可复用即映射，不另建同义实体。只使用专属worktree和合成测试数据库，不直接改部署目录。局部更优方案不破坏契约可记录后采用；跨组、数据归属、资金语义变更提交ADR，由集成人一次冻结。所有外部账号/密钥/报价/门店映射未核验项保留null，绝不能猜测或写入Git。

## 数据模型（候选映射）
Attribution(existing id,customer,origin_actor_type/id,source,state,confirmed_event); ServiceAssignment(customer,service_actor,consent,version); CommissionPolicyVersion(scope,effective_interval,base_definition,rate_bps,stage_coeff,eligible_sku); Accrual(source_fact,beneficiary,original_policy,delta_minor); Settlement(id,liability_refs,amount_minor,state). 归因原始历史不可覆写；H唯一付款。

## 界面与业务动作
客户/员工：我的推荐码、已确认推荐与佣金进度（不泄露被推荐者详细消费）；HQ：政策编辑、试算、审批、归因纠偏、待结算；财务付款状态由H投影。

## 可执行工作顺序
E-01. 复用现有邀请/认领/佣金政策及退款事件；扩actor_type+existing ID，不把普通客户伪造为TR
E-02. 候选来源→客户确认→真实首访/消费确认；同一客户只按批准规则归因；服务联系人可交接不改变原来源
E-03. 政策版本按范围与时间确定，费率和基数独立引用；同范围冲突拒绝，未批准不计可付；不公开真实比率
E-04. 真实履约+H验证付款/平台结算汇合后算累计目标，delta=新目标-历史已记；分次付款/退款累计计算，原订单政策不变
E-05. 应付→审批锁定→H付款→回执；已支付退款生成合法待调整，不直接扣个人账户；普通消费者单层直接推广，不按人数或下线计酬

## 操作合同
- cx.referral.claim.v1: invite_ref:id?,customer_confirmation_ref:id → attribution_id:id,state:s；候选/确认分离，已确认不覆盖
- cx.commission.accrue.v1: verified_payment_event_id:id,fulfillment_ref:id → accrual_id:id,delta_minor:i,state:s；累计差额、原政策；不得直接付款
- cx.commission.reverse.v1: refund_id:id → adjustment_id:id,delta_minor:i；真实退款；重复事件无新差额
- cx.commission.eligible.v1: cursor:s? → liabilities:objs,next_cursor:s?；本人或获权财务；非储值
- cx.referral.invite.v1: store_id:id? → invite_ref:id,expires_at:t；资格与用途；不自动现金推广
- cx.commission.policy.publish.v1: candidate_policy_id:id,approval_ref:id → policy_version:id,effective_at:t；试算、审批、同范围冲突拒绝
- cx.commission.settlement.prepare.v1: beneficiary_id:id,liability_ids:ids → settlement_id:id,amount_minor:i,state:s；锁定已核准负债，H付款
- cx.referral.correct.v1: attribution_id:id,correction_ref:id,approval_ref:id → correction_id:id,state:s；留原历史，不重复佣金
- cx.service.relationship.update.v1: customer_id:id?,assignment_ref:id,consent_ref:id → relationship_id:id,state:s；服务联系与原始推荐人分离

## 验收样例（尚未运行）
|ID|前置/操作|预期|
|---|---|---|
|E01|10000分、600bps、退款3000分（合成）|600分入账，-180分冲正，重复无新增|
|E02|修改佣金费率后旧单退款|使用旧版费率|
|E03|员工与消费者重复推荐|只按批准归因规则分配|
|E04|demo付款/未履约/平台券面值|不产生可付|
|E05|离职与联系人交接|客户资产与原始归因保持|

## 交付
归因状态机、政策表单字段、应付投影及H结算接口；真实费率、合同税务留空。
