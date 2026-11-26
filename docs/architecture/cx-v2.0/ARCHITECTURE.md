# 统一架构与契约
一套现有平台、三端（客户H5、现有员工POS、HQ）、八个工作线，不等于八个服务。保留14根目录、既有部署和权威域；函数优先，跨实际进程才受控API，跨事务需要时用现有outbox/inbox，不新建Kafka/网关/配置中心。
## 权威域
tenant_id partnership；legal_entity/store organization；auth_subject identity_access；employee workforce；product/bundle/publication catalog；customer/consent/loyalty customer；order/quote/booking commerce；payment/refund/reconciliation payments；attribution marketing；settlement operating_finance；policy_id compliance；task service_ops。A是引用目录，不另建政策权威；B身份、C公开投影、D非现金资产、E归因与应付、F/POS订单履约、G核销事实、H资金事实。以既有config/data-ownership为准。各企业独立逻辑数据库、独立最小权限角色；初期保留BSV实际权威库，不强迁SQLite。
## URA
CAP/OP/SRC/POL/RES/FLAG/ADP引用及旧别名；路径/商户/可变政策走批准配置；纯算法/安全不变量在代码。可信tenant+scope+ref+as_of→适用版本→权限/授权/健康→批准绑定，门店>法人>企业，法规底线不可覆盖，冲突拒绝。新操作用新版本，历史订单使用原配置/政策；公开读取可退审核快照；资金、权限、订单写失败关闭。未发送资金可选择获权备用；可能发送、UNKNOWN必须原单查证不可成功终态才能切换；独立库故障不能自动写另库。密钥只私有受控存储；禁止任意URL/动态代码。协议变化只改适配器，业务不重写。政策模板在CONFIG/POLICIES.json，合法性与参数组合由domain owner检查。
## 契约
OPERATIONS是编号，PAYLOAD-SCHEMAS是候选结构唯一源。已有线上接口映射，破坏语义须新版本，不直接覆盖。外层RequestEnvelope/ResponseEnvelope与所选payload分别验证；context_ref由服务端可信上下文生成。P公开限频/U本人/V现场visit/T门店员工/Q授权HQ/S可信内部/X签名回调；对象级、字段级权限逐项校验（OWASP）。写入幂等 tenant+op+actor+key，规范请求hash，异参拒绝。钱整数分+币种，UTC；选项min≤max、合法组合、报价逐项和总额/优惠/权益版本/主体/门店/有效期服务端校验，quote_id/digest不可伪造。PENDING/UNKNOWN不是成功。schema不能证明权限或资金正确。
## 事务及恢复
外部写先事务持久化DISPATCHING/原binding/外部单号后I/O。未知保留allocation/hold；查询原供应商，确认不可成功终态后释放。退款/撤销成功+在途≤原金额/份数；迟到异常成功对账，不删事实。事件producer唯一，event_id+tenant去重，outbox与事实同事务；payload_ref为受控不可变对象。事件目录EVENTS.json。
## 并行
8 worktrees；共享入口、迁移、POS由唯一owner；遵守AGENTS.md及官方迁移控制面。A-H可用同一fixture并行，不重做其他组；H依赖F报价，E依赖H/F，D依赖H/F，G→F→H，事件连接非启动循环。局部等效自主优化；共享合同、数据权威、安全/资金及正式发布才协调。旧系统改造见LEGACY.md，按实际缺口增量，不全局重构。