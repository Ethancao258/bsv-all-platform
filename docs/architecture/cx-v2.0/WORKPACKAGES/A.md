# CX-WP-A｜企业与URA
共同研发建议，不是强制步骤；MUST见ARCHITECTURE；局部等效优化可直接采用。初始只读START-HERE、本文件及公共ARCHITECTURE；按需查INDEX，不重复读历史。
## Route and evidence
现有受保护配置文件/注册表 + 进程内解析器；活动指针原子替换，启动时加载已批准版本。
Alternative: 现有PostgreSQL配置表作为共享外部配置存储（无需新服务），配置变更事务提交+版本指针，实例按版本检查刷新。
多个进程或企业需要统一配置、已有可靠PG时更合适；否则文件更短。Microsoft外部配置模式明确支持数据库作为后端。
Adopt if: 同一变更同时供2个既有进程使用且文件方案无法一致刷新，或现有HQ已有配置管理可直接复用；双租户、恢复、回切均通过。单企业不为此强迁。
Sources: https://learn.microsoft.com/azure/architecture/patterns/external-configuration-store ; https://www.postgresql.org/docs/17/ddl-constraints.html
## Concrete execution recommendation
单一resolver输入可信tenant+ref+scope+as_of，读取active revision；按门店>法人>租户选择唯一候选，再校验权限/授权/feature/健康；不返回密钥。配置候选dry-run→批准→CAS→新操作读取新版本，旧操作继续旧binding。数据库路由的引导引用留在受控启动配置。审批同一人不得兼任高风险批准者。

## 最小可交付切片
可信租户→引用配置→版本CAS→两租户/恢复→HQ配置；历史交易钉旧版本。
## 真实复用证据（历史SHA，运行态未知）
services/api/supply/gateway.py:18–65 Gateway.read/write — reuse pattern only; cache authorization and tenant/version isolation
integrations/auth/identity_client.py:15–74 request_identity/authorize_pos/authorize_device — extend bindings; preserve live permission checks
## 所属代码及业务对象
共享引用/配置/企业开户模块；实际路径由总集成人一次确认；不得擅自改供货/身份owner代码

TenantBinding(tenant_id,domain_ref,db_ref,legal_entity_refs,state); RefDefinition(ref_id,type,owner,contract_version); Binding(ref_id,tenant,scope,environment,revision,adapter_ref,secret_ref,priority,state); PolicyVersion(policy_id,scope,revision,effective_from,effective_to,params,approval_ref); Activation(scope,active_revision,prior_revision,actor,time). 可用现有受控文件及数据库存储，非要求建五张表。

## 界面与业务动作
HQ→企业选择→引用配置（能力/主备/适用入口/授权状态）→候选变更→校验与试算→批准→激活→回切；只显示脱敏凭据引用。企业开户表：企业/法人/门店/业态/数据库引用/初始管理员/商户绑定/政策模板，未知留空。


## 界面与验收
页面：A-CONFIG。复用三端壳，UI/PAGES与DESIGN按需查；本组12项功能按accountable_owner过滤FEATURE-TRACE，操作按owner查INDEX，必要时与delivery_owner合作；schema使用唯一CONTRACTS文件，不逐个创建HTTP。按合成FIXTURES/CASES测试，真实配置留空，外部授权未取得不假装可用。对真实运行路径不明项先只读核实。
## 可直接复制的启动指令
领取CX-WP-A。从总集成人确认的共同开发基线及独立worktree读取START-HERE、ARCHITECTURE、本任务书。选择现有代码复用、首选、备选或更短等效路径，记录证据；按最小切片实现和测试。只改本组文件；共享文件、迁移及POS由真实owner协调。未获授权标BLOCKED_LIVE，使用合成fixture继续开发；不改运行目录、不未经审批部署。交付SHA、功能ID、测试证据、阻断与回退。局部优化无需反复申请。