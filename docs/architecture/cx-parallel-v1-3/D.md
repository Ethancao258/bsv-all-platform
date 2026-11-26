# CX-WP-D｜权益、存酒、计时 V1.3
本文件为建议实施规格，不是代码、已上线接口或真实配置。上版V1.1/1.2历史保留；本版细化优先，现行已批准契约/源码约束优先于设计假定。执行者先对照最新主机基线及既有owner，原表/接口可复用即映射，不另建同义实体。只使用专属worktree和合成测试数据库，不直接改部署目录。局部更优方案不破坏契约可记录后采用；跨组、数据归属、资金语义变更提交ADR，由集成人一次冻结。所有外部账号/密钥/报价/门店映射未核验项保留null，绝不能猜测或写入Git。

## 数据模型（候选映射）
Entitlement(existing id,customer,template_version,unit,issued_qty,valid_from,to,state); Hold(id,entitlement,quote,qty,state,expires_at); Ledger(event_id,asset_id,delta,reason,source_ref); Custody(id,physical_label,store,product,customer,unit,expiry,staff); TimerSession(id,visit,product,policy_version,start,end,intervals,state). 余额为流水投影；非现金不与H本金合并。

## 界面与业务动作
顾客：权益/存酒/计时查询、申请；员工：扫码客户、存酒贴标、实物确认取酒、开启结束计时；HQ：权益模板、发放名单预览、有效期、适用门店/叠加、核销异常。

## 可执行工作顺序
D-01. 复用Benefit/Reservation已有模型，政策化期限/返场/同行/SKU/互斥；首访以符合条件的唯一visit事实触发，不把同桌加单当第二次
D-02. 原子预占：可用=发放+调整-消费-活动预占；并发锁定，绑定报价，未知外部支付不释放；退款按合同冲正
D-03. 总部发放来源事件唯一键，名单dry-run，营销同意与资产发放区分；礼券转让只允许规则且原持有人不可继续用
D-04. 存酒实物唯一标签、门店、最小计量单位、办理人、有效期；取酒F待办，员工实物确认才扣减；到期处置依告知和法律
D-05. 计时采用服务器时间、冻结费率和区间；续时升档保留版本/报价；积分/次卡独立计量；H商城成功支付后D幂等发放

## 操作合同
- cx.entitlement.list.v1: cursor:s? → entitlements:objs,next_cursor:s?；本人资产
- cx.entitlement.reserve.v1: entitlement_id:id,visit_id:id,quantity:i,quote_id:id → reservation_id:id,expires_at:t,state:s；事务锁定；数量>0；关联报价
- cx.entitlement.consume.v1: reservation_id:id,fulfillment_ref:id → ledger_id:id,state:s；仅可信履约/支付条件满足
- cx.entitlement.release.v1: reservation_id:id,evidence_ref:id → state:s；外部状态UNKNOWN不释放
- cx.custody.adjust.v1: custody_id:id,quantity:i,unit:s,action:s,reason:s → ledger_id:id,balance:i；员工现场实物确认；数量守恒
- cx.timer.status.v1: service_session_id:id → state:s,server_now:t,remaining_seconds:i?,elapsed_seconds:i；本人或授权会话
- cx.entitlement.issue.v1: customer_id:id,template_ref:id,source_event_id:id,quantity:i → entitlement_id:id,policy_version:id；总部批量或可信事件，唯一发放键
- cx.custody.request.v1: custody_id:id,quantity:i → task_id:id,state:s；仅创建F任务，不扣存酒
- cx.timer.start.v1: visit_id:id,product_id:id → service_session_id:id,start_at:t,policy_version:id；按POS已确认资格启动
- cx.timer.end.v1: service_session_id:id → state:s,elapsed_seconds:i,charge_quote_ref:id?；冻结时长并经F报价
- cx.custody.create.v1: customer_id:id,product_id:id,quantity:i,unit:s,physical_label:id → custody_id:id,expires_at:t；实物唯一标签、门店与员工来源
- cx.entitlement.adjust.v1: entitlement_id:id,delta:i,evidence_ref:id → ledger_id:id,balance:i；退款/纠偏冲正；不可负
- cx.timer.change.v1: service_session_id:id,action:s,quote_ref:id? → state:s,policy_version:id；续时升档须明确报价与资格
- cx.gift.transfer.v1: entitlement_id:id,recipient_proof_ref:id → transfer_id:id,state:s；授权可转让，双方确认，持有人唯一

## 验收样例（尚未运行）
|ID|前置/操作|预期|
|---|---|---|
|D01|最后1次并发2个hold|仅一个成功|
|D02|预占超时但付款UNKNOWN|不释放，查询原单|
|D03|同一首访两次加单|不重复发放或触发返场|
|D04|存酒700ml取200ml后再取600ml|余额500ml，拒绝第二次|
|D05|计时120分钟跨午夜/客户端时钟错误|服务器同一结束时间|
|D06|权益转赠后原持有人核销|拒绝|

## 交付
权益与存酒流水、计时接口、员工/HQ交互及现有权益回归；未查实物寄存旧实现前不新增权威表。
