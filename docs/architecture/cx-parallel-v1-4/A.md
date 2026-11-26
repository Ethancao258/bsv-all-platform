# CX-WP-A V1.4 | URA与租户
This is implementation advice, not a mandatory procedure. Use actual host findings to improve it. No live code or activation.
## Route and evidence
现有受保护配置文件/注册表 + 进程内解析器；活动指针原子替换，启动时加载已批准版本。
Alternative: 现有PostgreSQL配置表作为共享外部配置存储（无需新服务），配置变更事务提交+版本指针，实例按版本检查刷新。
多个进程或企业需要统一配置、已有可靠PG时更合适；否则文件更短。Microsoft外部配置模式明确支持数据库作为后端。
Adopt if: 同一变更同时供2个既有进程使用且文件方案无法一致刷新，或现有HQ已有配置管理可直接复用；双租户、恢复、回切均通过。单企业不为此强迁。
Sources: https://learn.microsoft.com/azure/architecture/patterns/external-configuration-store ; https://www.postgresql.org/docs/17/ddl-constraints.html
## Concrete execution recommendation
单一resolver输入可信tenant+ref+scope+as_of，读取active revision；按门店>法人>租户选择唯一候选，再校验权限/授权/feature/健康；不返回密钥。配置候选dry-run→批准→CAS→新操作读取新版本，旧操作继续旧binding。数据库路由的引导引用留在受控启动配置。审批同一人不得兼任高风险批准者。
## New/revised operations
- cx.tenant.resolve.v1: host:s,session_ref:id? → tenant_id:id,legal_entity_ids:ids,config_revision:id; 可信路由/会话一致，禁止浏览器指定数据库
- cx.provider.resolve.v1: reference_id:id,channel:s,store_id:id? → binding_id:id,adapter_id:id,config_revision:id,eligible:b; 返回脱敏绑定，凭据仅内部受控对象
- cx.flag.read.v1: feature_id:id,store_id:id? → enabled:b,revision:id,reason:s; 服务端强制，不以UI隐藏替代
- cx.reference.resolve.v1: reference_id:id,operation_id:id,context_ref:id? → binding_id:id,revision:id,kind:s; 无候选拒绝，不接受任意URL
- cx.policy.resolve.v1: policy_id:id,scope_ref:id,as_of:t → policy_version:id,parameters:obj; 唯一适用版本，冲突拒绝
- cx.config.activate.v1: candidate_id:id,expected_revision:id,approval_ref:id → revision:id,prior_revision:id; CAS原子发布；审批权限来自已有身份域
- cx.config.stage.v1: reference_id:id,scope_ref:id,patch:obj → candidate_id:id,validation_state:s; 白名单配置字段；不接受明文secret
- cx.tenant.provision.v1: onboarding_ref:id,profile_id:id,approval_ref:id → tenant_id:id,state:s; 复用现有编号，DB及凭据创建受控
- cx.config.rollback.v1: revision:id,expected_revision:id,approval_ref:id → active_revision:id; 只影响新操作，保留历史交易
- cx.provider.health.v1: reference_id:id,store_id:id? → candidates:objs,observed_at:t; 授权与技术健康分开
## Deliverable and tests
Read FEATURE-TRACE filtered by accountable_owner and CRITICAL-CASES. Related-only entries need explicit UI/domain work, not false pass. Preserve old code when equivalent. Actual paths and schema mapping validated on host; missing binding null. Compare alternatives using observed implementation effort and recurring fee, authorization, error recovery and rollback. No claim of global best. 
## V1.3 inherited scope (historical, signatures superseded above)
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

