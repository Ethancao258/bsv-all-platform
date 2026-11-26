# CX-WP-F｜POS到店服务
共同研发建议，不是强制步骤；MUST见ARCHITECTURE；局部等效优化可直接采用。初始只读START-HERE、本文件及公共ARCHITECTURE；按需查INDEX，不重复读历史。
## Route and evidence
客户提交现有POS待确认草稿，员工接单；内部调用或现有受限HTTP，单一订单写源。
Alternative: POS原有写入事务 + transactional outbox/inbox 自动接单与异步履约投影；保留员工确认作为门店开关。
AWS事务发件箱模式解决业务提交与事件发送双写风险；仅使用现有数据库，消费者幂等，不需要AWS/Kafka。
Adopt if: POS负责人证明实际订单可原子提交，库存/年龄/权限/价格实时校验且重放无重复；自动接单试点失败率和人工纠错成本不高于人工确认，否则保持草稿。
Sources: https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html ; https://developer.meituan.com/docs/biz/biz_rms_e8a2bfb2-c855-40ff-8565-ee946a5cae2e
## Concrete execution recommendation
静态桌码定位，短期join proof绑定tenant/store/visit/actor；结束撤权。quote服务端算并锁版本；submit按同幂等键同参数复用原order；员工accept按expected revision单写。预约半开区间冲突锁；队列单调序号；服务任务按权限状态更新。G事实写订单使用唯一external_fact_id，H支付结果只更新已核验事实。

## 最小可交付切片
现场短期proof→购物车CAS→服务端quote→POS接单→履约事件；预约资源锁/活动/候位/待办；F唯一报价权威。
## 真实复用证据（历史SHA，运行态未知）
services/api/bsv1/app.py:476–489 live_visit/order_for/get_lines — reuse candidate; POS owns write
services/api/bsv1/bsv_growth_pos.py:82–108 make_guest_link/verify_guest_link/make_visit_context — proof reuse only; read proof not order authority
services/api/bsv1/app.py:1236–1381 growth_customer_link/growth_visit_context/growth_visit_verify — extend candidate; scoped join
services/api/bsv1/app.py:1922–2115 do_GET /api/state,/api/history,/api/receipt — private projection; never expose raw staff state
## 所属代码及业务对象
既有POS owner协调桥接及客户服务模块；不另建订单库

Visit与Order由既有POS拥有；GuestAccess(visit,actor,scope,nonce,expiry,state); Booking(resource,start,end,capacity,state,revision); QueueTicket(store,party,seq,state); ServiceTask(visit/customer,kind,priority,state,assignee,revision); Outbox(event_id,producer,payload,state,attempts) 复用已有事件设施；通知投影非订单事实。

## 界面与业务动作
扫码定位→员工批准/短期加入凭证→购物车→价格确认→提交待接单→已接单/出品；员工POS统一待办。预约/候位/包场/活动先申请确认；现场呼叫、换桌、取酒、反馈统一入口。


## 界面与验收
页面：F-CART、F-ORDER、F-BOOKING、F-EVENTS、F-SERVICE、F-NOTICES、F-FEEDBACK、F-STAFF。复用三端壳，UI/PAGES与DESIGN按需查；本组54项功能按accountable_owner过滤FEATURE-TRACE，操作按owner查INDEX，必要时与delivery_owner合作；schema使用唯一CONTRACTS文件，不逐个创建HTTP。按合成FIXTURES/CASES测试，真实配置留空，外部授权未取得不假装可用。对真实运行路径不明项先只读核实。
## 可直接复制的启动指令
领取CX-WP-F。从总集成人确认的共同开发基线及独立worktree读取START-HERE、ARCHITECTURE、本任务书。选择现有代码复用、首选、备选或更短等效路径，记录证据；按最小切片实现和测试。只改本组文件；共享文件、迁移及POS由真实owner协调。未获授权标BLOCKED_LIVE，使用合成fixture继续开发；不改运行目录、不未经审批部署。交付SHA、功能ID、测试证据、阻断与回退。局部优化无需反复申请。