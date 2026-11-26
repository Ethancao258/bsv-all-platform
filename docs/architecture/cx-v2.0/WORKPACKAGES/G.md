# CX-WP-G｜团购核销
共同研发建议，不是强制步骤；MUST见ARCHITECTURE；局部等效优化可直接采用。初始只读START-HERE、本文件及公共ARCHITECTURE；按需查INDEX，不重复读历史。
## Route and evidence
收钱吧智慧经营聚合核销；人工官方端作为低风险备用。
Alternative: 美团官方顾客点餐自助核销 + 抖音官方券准备/核销/券状态查询两适配器。
直接获得平台原生能力及独立退出路径；美团明确支持品牌小程序自助验券，抖音查询接口要求验券准备返回的encrypted_code，不能用明文替代。
Adopt if: 聚合未获消费者自主核销或ISV授权、报价/异常恢复不合格，而平台直连实测可用；或业务量使维护净成本更低。若两边未授权，人工官方核销，不模拟真实成功。
Sources: https://doc.shouqianba.com/docs-for-smart/ ; https://developer.meituan.com/isv/daocan/ ; https://developer.open-douyin.com/docs/resource/zh-CN/local-life/develop/OpenAPI/general-capabilities/life.capacity.fulfilment/certificate.get ; https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/open-capacity/solutions/life-service-solutions/verification-tool
## Concrete execution recommendation
先查券/确认平台、门店、SKU与份数→持久化consume attempt和原binding/requestId→发送→原单查询→确认核销事实→F幂等补单。撤销必须针对具体consume_attempt，成功+在途撤销数量不得超已核销。业务状态与POS履约状态分开；H结算到账才算收入。

## 最小可交付切片
查券选份→持久化attempt→平台确认→F补单→H实际结算→原attempt部分撤销；未知查原单。
## 真实复用证据（历史SHA，运行态未知）
UNKNOWN:?  — UNKNOWN; provider authorization, actual adapter, SKU mapping
## 所属代码及业务对象
现有integrations/marketplaces下适配器及核销事实模块；F订单

CouponIntent(id,tenant,store,platform,code_ref,query_version,expires_at,offer_mapping_version); ConsumeAttempt(id,intent,provider_binding,request_id,count,state,sqb_order_id?,external_order_ref?); ExternalFact(id,platform,store,provider_fact_ref,count,state); CancelAttempt(id,consume_ref,request_id,count,success_count,failed_count,state); FulfillmentLink(external_fact_id,order_id,state). 供应商返回的码短期加密，日志仅掩码。

## 界面与业务动作
客人选择美团/抖音→输入券码→查券显示套餐及可核数量→选择份数与确认→核销处理中/成功待接单/已接单。员工可见未决、补单、部分撤销、人工官方验券证据；HQ对账。


## 界面与验收
页面：G-REDEEM、G-STAFF。复用三端壳，UI/PAGES与DESIGN按需查；本组6项功能按accountable_owner过滤FEATURE-TRACE，操作按owner查INDEX，必要时与delivery_owner合作；schema使用唯一CONTRACTS文件，不逐个创建HTTP。按合成FIXTURES/CASES测试，真实配置留空，外部授权未取得不假装可用。对真实运行路径不明项先只读核实。
## 可直接复制的启动指令
领取CX-WP-G。从总集成人确认的共同开发基线及独立worktree读取START-HERE、ARCHITECTURE、本任务书。选择现有代码复用、首选、备选或更短等效路径，记录证据；按最小切片实现和测试。只改本组文件；共享文件、迁移及POS由真实owner协调。未获授权标BLOCKED_LIVE，使用合成fixture继续开发；不改运行目录、不未经审批部署。交付SHA、功能ID、测试证据、阻断与回退。局部优化无需反复申请。