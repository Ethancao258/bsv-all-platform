# CX-WP-A｜租户、路由与功能开关 V1.2
状态：DESIGN_READY，非已实现、非已部署。阅读上版 ../cx-parallel-v1-1/README.md、CONTRACT.md、REGISTRY.json 及对应任务书；本版增量补充，冲突以本版设计建议为准，既有 AGENTS.md 与已批准正式契约优先。源码证据基线 2052ef51f011be3c5898d816932d8982f420b752；最新主机状态须由集成人复核。所有路径/表/字段为拟议映射，不是已创建对象。

业务范围：CX-19、CX-20；旧模块编号与候选路径保留：services/api/shared/cx/、tests/cx/A/。功能逐项索引见 FEATURES.md；新增操作见 OPERATIONS.json。

## 决策与备选
首选扩展既有 shared/data_contracts、data router、供货配置/网关的公共原则，先实现进程内 resolver + 版本化配置/受保护存储；不引入新配置中心服务、规则DSL运行器、Kubernetes或服务网格。初期单企业保持现有权威源，增加同一代码两套独立合成库的测试。逐企业数据库较共享表隔离更直观；共享物理实例不是物理隔离。未来可按租户迁到独立实例。不得因设计多租户强迁当前POS SQLite。
## 实现顺序
A1 核对现有租户归属与数据源注册；建立统一 URI-free 逻辑引用解析接口（URA.md），保留 identity.A/supply.A 等旧别名映射。A2 为租户生成独立DB连接凭证引用、应用身份、门店法人映射；根据可信域名/已验会话确定租户，拒绝客户端指定任意库。连接池懒加载、有限容量、TTL回收；配置服务或DB不可用时不对关键写入使用过期路由。A3 实现候选→校验→批准→激活→退役的原子配置指针；按租户、能力、操作、入口环境、门店定义适用性/优先级；选择结果带config_revision。A4 适配器工厂+能力列表、超时/熔断/半开探测、故障分类；资金按H状态机。A5 统一政策引用/版本和服务端开关、只读配置/审计后台原型；真实审批权限复用身份域。A6 提供注册校验、两个合成租户、统一fixture与错误矩阵；以契约为边界不要求其他工作组等底座实现完成才编码。
## 候选数据/接口
tenant_id 现归 partnership；legal_entity/store归organization；policy_id 现归compliance，具体策略规则由业务域拥有（政策目录只引用、不可成为第二政策事实）。候选注册实体：reference_definition(id,kind,owner,contract), binding(tenant,environment,scope,reference_id,revision,provider/adapter_ref,secret_ref,policy_ref,health_class,state), config_activation(revision,actor,approval,time,prior_revision)。数据库schema由集成人审核，首版可用版本化配置文件+受保护凭据，后续增量接管理UI，不强行新建表。对内 resolve/reference、resolve_policy/evaluate、flag.read；返回绑定版本/选择原因，不返回密钥。
## 验收/反例
两个租户使用相同商品显示码、不同数据库/政策/商户凭据；跨租户访问/回调/缓存/任务/备份必须拒绝。支付渠道失败不可重发未知交易；配置非法主机、重定向、权限扩张、任意代码/SQL、循环引用拒绝。20次并发配置读取仅见完整旧/新版本，数字为测试样例非容量承诺。策略回切仅影响新操作，旧交易继续使用原快照。参考 Microsoft External Configuration Store、Circuit Breaker 与 PostgreSQL角色文档。

## 给腾讯云执行Agent的合作规则
本设计是当前证据下的首选路径，不是不可修改的命令。你负责实机复核、提出更短/更优方案及实施。若发现既有实现可直接复用、平台接口变更或冲突，不重复研发：提交一条变更提议（原方案、实际代码/官方证据、替代方案、节省的变更/维护量、影响契约/数据/风险、测试与回退）。不改变外部契约、不降低安全、不改变产品目标且不抢其他路径的局部优化，可在所属分支直接实施并记录；共享契约、财务语义、数据归属、生产发布、法律约束变更由集成人/负责人审定，一次广播新版本。反例有证据则修正规范，不要求Agent重复完整需求研究。
开发仅限独立worktree、合成fixture、指定路径。禁止改运行release、共享数据库、公开路由、他组文件、实际支付/核销或生产DDL。依赖未就绪时只用统一fixture；不自行实现依赖方的业务逻辑。输出步骤逐项PASS/FAIL/MOCK_ONLY/NOT_RUN、代码位置、证据、PR/SHA、配置/迁移影响、回退及实机未决门槛。
