# CX-WP-D｜权益存酒计时
共同研发建议，不是强制步骤；MUST见ARCHITECTURE；局部等效优化可直接采用。初始只读START-HERE、本文件及公共ARCHITECTURE；按需查INDEX，不重复读历史。
## Route and evidence
现有Benefit/Reservation行锁+唯一键+流水，同事务扣减。
Alternative: PostgreSQL条件UPDATE RETURNING/版本CAS，原子库存余额扣减+同事务插入流水和幂等记录；可用于高并发单资产，非另建账本。
PG17支持UPDATE RETURNING；单行条件更新可减少一次读锁往返。多资产组合仍需事务及固定锁顺序。
Adopt if: 现有行锁实现简单可靠则保留；只有实际争用、性能或原子更新更易复用时采用条件更新；并发、重复、回滚、负余额、锁死均验证。
Sources: https://www.postgresql.org/docs/17/sql-update.html ; https://www.postgresql.org/docs/17/dml-returning.html ; https://www.postgresql.org/docs/17/explicit-locking.html
## Concrete execution recommendation
可用=已发行+调整-已消费-活动预占。预占唯一键（asset,quote,request）；锁资产、校验范围/时效/资格、扣可用+建hold；支付未知到期转REVIEW不释放。消耗与释放是互斥终态。存酒qty用最小单位；标签、员工、门店、expiry；到期进入待处置不删。计时区间按UTC取交集、暂停扣除，费率引用原版本，金额由F报价。

## 最小可交付切片
发放→可用资格→报价预占→可信履约消耗/确认未发生释放；未知保持锁；实物取酒员工确认，计时UTC，H退款驱动。
## 真实复用证据（历史SHA，运行态未知）
services/api/customer_growth/app.py:207–236 MembershipCycle/Benefit/BenefitReservation — reuse candidate; hold/quantity, custody/timer UNKNOWN
services/api/customer_growth/app.py:1116–1167 /internal/benefits/reserve — extend candidate; verify unknown external result before release
## 所属代码及业务对象
客户资产/计时扩展及员工组件；F资源owner，H资金owner

Entitlement(existing id,customer,template_version,unit,issued_qty,valid_from,to,state); Hold(id,entitlement,quote,qty,state,expires_at); Ledger(event_id,asset_id,delta,reason,source_ref); Custody(id,physical_label,store,product,customer,unit,expiry,staff); TimerSession(id,visit,product,policy_version,start,end,intervals,state). 余额为流水投影；非现金不与H本金合并。

## 界面与业务动作
顾客：权益/存酒/计时查询、申请；员工：扫码客户、存酒贴标、实物确认取酒、开启结束计时；HQ：权益模板、发放名单预览、有效期、适用门店/叠加、核销异常。


## 界面与验收
页面：D-RIGHTS、D-CUSTODY、D-TIMER、D-STAFF、D-HQ。复用三端壳，UI/PAGES与DESIGN按需查；本组30项功能按accountable_owner过滤FEATURE-TRACE，操作按owner查INDEX，必要时与delivery_owner合作；schema使用唯一CONTRACTS文件，不逐个创建HTTP。按合成FIXTURES/CASES测试，真实配置留空，外部授权未取得不假装可用。对真实运行路径不明项先只读核实。
## 可直接复制的启动指令
领取CX-WP-D。从总集成人确认的共同开发基线及独立worktree读取START-HERE、ARCHITECTURE、本任务书。选择现有代码复用、首选、备选或更短等效路径，记录证据；按最小切片实现和测试。只改本组文件；共享文件、迁移及POS由真实owner协调。未获授权标BLOCKED_LIVE，使用合成fixture继续开发；不改运行目录、不未经审批部署。交付SHA、功能ID、测试证据、阻断与回退。局部优化无需反复申请。