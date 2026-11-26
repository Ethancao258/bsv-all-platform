# CX-WP-F｜POS桥、到店会话、预约与服务任务
状态 DESIGN_ONLY；独立研究与执行任务书。
业务编号：CX-05、CX-07、CX-12、CX-13、CX-14、CX-17、CX-27、CX-28、CX-32。
模块：VISITSESSION、CXORDER、BOOKING、CXCARE、CXMSG、CXANALYTICS。
候选专属路径：services/api/customer_growth/cx_visit/、apps/guest-web/cx-visit/、tests/cx/F/（开工时与实际路径/既有owner核对，必要时集成人一次性调整）。
数据域：commerce、service_ops、event_audit、organization；既有数据所有权不改变。
操作编号：cx.visit.join.v1、cx.order.submit.v1、cx.order.status.v1、cx.order.external_fulfill.v1、cx.booking.request.v1、cx.service.request.v1。
联调依赖：A、B、C；开发可立即使用冻结fixture。
生产门槛：既有POS负责人批准桥接；真实订单权威和桌次安全验收。

## 研究与最短实现
已有 POS seats/visits/orders/drafts/production/history 等接口及幂等 _action_id，复用现有 visit_id/order_id，不创建第二订单库。既有POS员工权限不能直接赋予消费者；永久桌码仅定位，短期一次性加入凭证/员工确认绑定活跃visit及客户会话。顾客通过受限命令提交草稿或员工待办，POS负责人唯一拥有真实订单写入；必须服务端重新计价、SKU/套餐限制、门店售罄及当前桌次检查。接口桥只增加明确的受权操作，不调用任意POS路径。换桌保持visit，结束撤销token，多人账单只返回授权明细；禁止远程扫旧桌码提交。
预约先申请+员工确认，后续时间区间排斥约束/容量限制；候位FIFO/超时，活动和包场共用预约资源。服务请求统一状态机、幂等、防刷、安全求助优先。消息通过业务事件+站内通知，微信订阅需用户授权；低成本数据库outbox，不新建消息中间件。评价关联真实订单，区分浏览/收藏/付款/核销/复购。F只提供受控履约与订单事实，不把模拟结账变真实付款；外部券核销成功的订单由G调用唯一外部履约命令。
## 验收
过期/复制桌码、非本桌、跨店跨租户、无权限员工、重复提交、换桌/结束桌、商品售罄、价格变化、订单失败后重试；POS原功能全回归。未有POS桥接批准时开发mock，提供契约补丁给POS唯一负责人，不抢占现有POS研发。

## 全员通用执行指令
只领取本工作包；从集成人发布的同一不可变集成基线创建独立 Git worktree/分支，使用合成数据、隔离数据库与测试替身。先比对现有模块是否已有可复用函数，禁止重写。可在未获供应商授权时写契约测试、离线实现；不得声称真实接通。不得读取或修改其他Agent工作区、运行目录、共享数据库、端口、systemd、Nginx或生产资料。共享入口、数据字典、迁移登记、注册表、POS文件由集成人或既有POS负责人唯一写入；提交最小补丁请求。契约变更必须先冻结新版本并通知依赖方，不得单方面改变语义。
交付：变更文件清单、复用证据、业务流程及算法、测试结果（PASS/FAIL/MOCK_ONLY/NOT_RUN）、契约版本、迁移候选、回退、未解阻断、PR/SHA；不做部署。缺少真实授权时标 BLOCKED_LIVE，其他合成任务继续。禁用模块不得删除历史资产或重试未知资金交易。任何真实数据、密钥、商户凭证、私人经营政策不得提交Git。
