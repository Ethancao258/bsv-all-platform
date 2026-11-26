# CX-WP-A｜租户与URA V1.3
本文件为建议实施规格，不是代码、已上线接口或真实配置。上版V1.1/1.2历史保留；本版细化优先，现行已批准契约/源码约束优先于设计假定。执行者先对照最新主机基线及既有owner，原表/接口可复用即映射，不另建同义实体。只使用专属worktree和合成测试数据库，不直接改部署目录。局部更优方案不破坏契约可记录后采用；跨组、数据归属、资金语义变更提交ADR，由集成人一次冻结。所有外部账号/密钥/报价/门店映射未核验项保留null，绝不能猜测或写入Git。

## 数据模型（候选映射）
TenantBinding(tenant_id,domain_ref,db_ref,legal_entity_refs,state); RefDefinition(ref_id,type,owner,contract_version); Binding(ref_id,tenant,scope,environment,revision,adapter_ref,secret_ref,priority,state); PolicyVersion(policy_id,scope,revision,effective_from,effective_to,params,approval_ref); Activation(scope,active_revision,prior_revision,actor,time). 可用现有受控文件及数据库存储，非要求建五张表。

## 界面与业务动作
HQ→企业选择→引用配置（能力/主备/适用入口/授权状态）→候选变更→校验与试算→批准→激活→回切；只显示脱敏凭据引用。企业开户表：企业/法人/门店/业态/数据库引用/初始管理员/商户绑定/政策模板，未知留空。

## 可执行工作顺序
A-01. 核对现有shared data_contracts、change-routing、供货gateway；建立兼容别名，不引入第二注册体系
A-02. 先单进程解析函数：可信租户→业务引用→有效配置→适配器；公开读降级、关键写fail closed；无适配器则DISABLED
A-03. 建立两合成租户独立库、角色、对象存储路径、缓存、队列和回调隔离；不迁真实库
A-04. 配置版本指针CAS，scope按租户→法人→门店，冲突拒绝；禁止任意URL、动态代码；旧交易绑定旧版本
A-05. 先只读管理页再审批启用；新增企业复制模板而非复制源码；独立备份/恢复演练；停租户阻止新交易但保留合法售后

## 操作合同
- cx.tenant.resolve.v1: host:s,session_ref:id? → tenant_id:id,legal_entity_ids:ids,config_revision:id；可信路由/会话一致，禁止浏览器指定数据库
- cx.provider.resolve.v1: reference_id:id,channel:s,store_id:id? → binding_id:id,adapter_id:id,config_revision:id,eligible:b；返回脱敏绑定，凭据仅内部受控对象
- cx.flag.read.v1: feature_id:id,store_id:id? → enabled:b,revision:id,reason:s；服务端强制，不以UI隐藏替代
- cx.reference.resolve.v1: reference_id:id,operation_id:id,context_ref:id? → binding_id:id,revision:id,kind:s；无候选拒绝，不接受任意URL
- cx.policy.resolve.v1: policy_id:id,scope_ref:id,as_of:t → policy_version:id,parameters:obj；唯一适用版本，冲突拒绝
- cx.config.activate.v1: candidate_id:id,expected_revision:id,approval_ref:id → revision:id,prior_revision:id；CAS原子发布；审批权限来自已有身份域
- cx.config.stage.v1: reference_id:id,scope_ref:id,patch:obj → candidate_id:id,validation_state:s；白名单配置字段；不接受明文secret
- cx.tenant.provision.v1: onboarding_ref:id,profile_id:id,approval_ref:id → tenant_id:id,state:s；复用现有编号，DB及凭据创建受控
- cx.config.rollback.v1: revision:id,expected_revision:id,approval_ref:id → active_revision:id；只影响新操作，保留历史交易
- cx.provider.health.v1: reference_id:id,store_id:id? → candidates:objs,observed_at:t；授权与技术健康分开

## 验收样例（尚未运行）
|ID|前置/操作|预期|
|---|---|---|
|A01|租户T1/T2同商品ID、不同佣金配置|两边仅返回本企业数据|
|A02|启用V2时V1支付未决|V1继续查询原商户，新单使用V2|
|A03|配置缺密钥/URL、重复优先级、未知adapter|校验拒绝，原版本仍生效|
|A04|T1恢复备份|T2数据不变，T1待决资金先对账|
|A05|供应商授权到期|拒绝新请求，历史查询与退款依授权保留|

## 交付
最小解析器、引用登记、两租户测试、配置审批视图及恢复证据；无新长期进程。
