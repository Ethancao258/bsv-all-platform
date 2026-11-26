# CX-WP-F｜POS、预约、到店与服务 V1.3
本文件为建议实施规格，不是代码、已上线接口或真实配置。上版V1.1/1.2历史保留；本版细化优先，现行已批准契约/源码约束优先于设计假定。执行者先对照最新主机基线及既有owner，原表/接口可复用即映射，不另建同义实体。只使用专属worktree和合成测试数据库，不直接改部署目录。局部更优方案不破坏契约可记录后采用；跨组、数据归属、资金语义变更提交ADR，由集成人一次冻结。所有外部账号/密钥/报价/门店映射未核验项保留null，绝不能猜测或写入Git。

## 数据模型（候选映射）
Visit与Order由既有POS拥有；GuestAccess(visit,actor,scope,nonce,expiry,state); Booking(resource,start,end,capacity,state,revision); QueueTicket(store,party,seq,state); ServiceTask(visit/customer,kind,priority,state,assignee,revision); Outbox(event_id,producer,payload,state,attempts) 复用已有事件设施；通知投影非订单事实。

## 界面与业务动作
扫码定位→员工批准/短期加入凭证→购物车→价格确认→提交待接单→已接单/出品；员工POS统一待办。预约/候位/包场/活动先申请确认；现场呼叫、换桌、取酒、反馈统一入口。

## 可执行工作顺序
F-01. 复用既有POS visit/order/draft/action_id及客户关联证明；POS owner提供受限quote/submit/status/external_fulfill桥，不能给顾客员工token
F-02. 桌码仅定位，visit短期scope绑定；结束撤销，换桌保留visit；购物车价格服务端算，价格变化二次确认，D权益预占
F-03. 第一版客户提交员工确认草稿，稳定后通过功能开关自动接单；POS幂等写入；多人行权限、代付、拆账由H核验
F-04. 预约先人工确认；同资源半开时间区间互斥，容量资源在事务内锁；候位FIFO、活动名额、包场使用相同资源服务
F-05. 服务待办状态机、事件消息与营销授权；数据库outbox/inbox而非新消息服务；真实反馈关联订单，非消费意见独立；浏览/购买/履约统计分开

## 操作合同
- cx.visit.join.v1: seat_locator:id,join_proof:id → visit_id:id,access_ref:id,expires_at:t；现场证明与会话scope；游客受限
- cx.order.submit.v1: visit_id:id,items:items,quote_version:id → order_id:id,state:s,quote:obj；POS唯一写；重新计价与幂等
- cx.order.status.v1: order_id:id → order_id:id,state:s,authorized_lines:objs；仅授权行
- cx.order.external_fulfill.v1: visit_id:id,external_fact_id:id,items_snapshot:items → order_id:id,state:s；唯一外部事实行；G调用
- cx.booking.request.v1: resource_ref:id,start_at:t,end_at:t,party_size:i → booking_id:id,state:s；未确认不保证座位
- cx.service.request.v1: visit_id:id?,kind:s,details:obj → task_id:id,state:s；安全求助优先；防刷
- cx.booking.confirm.v1: booking_id:id,resource_ref:id,expected_revision:id → state:s,revision:id；资源锁与容量原子校验
- cx.booking.cancel.v1: booking_id:id,reason:s → state:s,refund_request_ref:id?；取消与退款事实独立
- cx.service.update.v1: task_id:id,action:s,expected_revision:id → state:s,revision:id；门店权限/状态转换
- cx.notify.list.v1: cursor:s? → messages:objs,next_cursor:s?；本人授权消息
- cx.feedback.submit.v1: order_id:id?,kind:s,content:s → feedback_id:id,state:s；评价有订单事实；其他意见可无订单
- cx.order.quote.v1: visit_id:id?,items:items,benefit_ids:ids? → quote_id:id,quote_version:id,total_minor:i,expires_at:t；唯一计价入口；非承诺库存
- cx.order.cancel.request.v1: order_id:id,reason:s → task_id:id,state:s；已出品/支付需员工审批及H退款
- cx.queue.join.v1: store_id:id,party_size:i → ticket_id:id,state:s；候位非预约
- cx.queue.update.v1: ticket_id:id,action:s → state:s,visit_id:id?；叫号、取消、员工入座
- cx.notify.mark_read.v1: message_id:id → read:b；不修改业务状态
- cx.service.status.v1: task_id:id → state:s,updated_at:t；本人/会话任务

## 验收样例（尚未运行）
|ID|前置/操作|预期|
|---|---|---|
|F01|关桌后重放旧join proof|拒绝|
|F02|价格变更或售罄|返回新报价或拒绝，不静默加价|
|F03|同幂等键重发/异参|同结果/冲突|
|F04|换桌|原visit与订单保留|
|F05|同一资源两个重叠确认|仅一个成功或容量内|
|F06|G外部事实重发|同一POS履约记录|
|F07|越权查同桌他人账单|拒绝或仅授权行|

## 交付
POS桥最小补丁请求、顾客页面、服务任务与预约模型；不创建第二套订单数据库。
