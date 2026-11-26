# CX-WP-E｜推荐佣金
共同研发建议，不是强制步骤；MUST见ARCHITECTURE；局部等效优化可直接采用。初始只读START-HERE、本文件及公共ARCHITECTURE；按需查INDEX，不重复读历史。
## Route and evidence
复用现有版本化政策表+类型化条件/费率计算，唯一规则解析，差额流水。
Alternative: DMN标准决策表（例如Camunda DMN UNIQUE hit policy）作为独立政策评估适配器；不替换佣金主账，不要求部署Camunda平台。
规则组合复杂时可视化冲突检查更好；简单费率/阶段不值得额外引擎。Camunda文档明确UNIQUE不允许多条匹配。
Adopt if: 实际存在大量互相交叉的政策条件、手工配置频繁冲突，且可用运行库、许可证、资源开销与同输入输出回归验证通过；否则保留SQL+类型化参数。
Sources: https://docs.camunda.io/docs/components/modeler/dmn/decision-table-hit-policy/ ; https://docs.camunda.org/get-started/dmn/model/
## Concrete execution recommendation
合格支付/结算减匹配退款；仅真实履约及已确认归因计佣。累计目标=round_half_up(net_minor×rate_bps×coeff_bps/1e8)，delta=target-已记。分配尾差按稳定line_id规则、总额守恒。以order/beneficiary/policy/component唯一聚合，事件去重；策略缺失只候选。H对账后更新应付状态，不调用资金接口。

## 最小可交付切片
候选→确认→真实履约/净实收→原政策累计差额→批准锁定→H付款→冲正；不按人数或下线计酬。
## 真实复用证据（历史SHA，运行态未知）
services/api/customer_growth/app.py:159–302 ClaimTicket/Claim/Attribution/Policy/Commission/CommissionLedger — reuse candidate; one commission authority
services/api/customer_growth/app.py:821–1169 staff_invite/claim/confirm_claim/commission_for/create_policy — reuse candidate; verify exact contract and real facts
## 所属代码及业务对象
现有customer_growth归因/佣金模块、财务应付投影；H实际付款

Attribution(existing id,customer,origin_actor_type/id,source,state,confirmed_event); ServiceAssignment(customer,service_actor,consent,version); CommissionPolicyVersion(scope,effective_interval,base_definition,rate_bps,stage_coeff,eligible_sku); Accrual(source_fact,beneficiary,original_policy,delta_minor); Settlement(id,liability_refs,amount_minor,state). 归因原始历史不可覆写；H唯一付款。

## 界面与业务动作
客户/员工：我的推荐码、已确认推荐与佣金进度（不泄露被推荐者详细消费）；HQ：政策编辑、试算、审批、归因纠偏、待结算；财务付款状态由H投影。


## 界面与验收
页面：E-REFERRAL、E-HQ。复用三端壳，UI/PAGES与DESIGN按需查；本组12项功能按accountable_owner过滤FEATURE-TRACE，操作按owner查INDEX，必要时与delivery_owner合作；schema使用唯一CONTRACTS文件，不逐个创建HTTP。按合成FIXTURES/CASES测试，真实配置留空，外部授权未取得不假装可用。对真实运行路径不明项先只读核实。
## 可直接复制的启动指令
领取CX-WP-E。从总集成人确认的共同开发基线及独立worktree读取START-HERE、ARCHITECTURE、本任务书。选择现有代码复用、首选、备选或更短等效路径，记录证据；按最小切片实现和测试。只改本组文件；共享文件、迁移及POS由真实owner协调。未获授权标BLOCKED_LIVE，使用合成fixture继续开发；不改运行目录、不未经审批部署。交付SHA、功能ID、测试证据、阻断与回退。局部优化无需反复申请。