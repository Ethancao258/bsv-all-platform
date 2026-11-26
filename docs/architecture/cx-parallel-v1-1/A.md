# CX-WP-A｜租户、路由与功能开关
状态 DESIGN_ONLY；独立研究与执行任务书。
业务编号：CX-19、CX-20。
模块：TENANT、PROVIDER、CXFLAGS。
候选专属路径：services/api/shared/cx/、tests/cx/A/（开工时与实际路径/既有owner核对，必要时集成人一次性调整）。
数据域：partnership、identity_access、event_audit；既有数据所有权不改变。
操作编号：cx.tenant.resolve.v1、cx.provider.resolve.v1、cx.flag.read.v1。
联调依赖：无；开发可立即使用冻结fixture。
生产门槛：A契约与两租户隔离通过；生产配置、迁移另批。

## 研究与最短实现
延伸已存在的数据源命名空间与 change-routing，不创建平行控制面；已有路由仅决策函数，不能宣称已具备租户连接。采用单代码多独立逻辑库，初期现有企业保持原权威写源；先用两个合成租户证明隔离，不迁库。tenant_id 归 partnership，legal_entity_id/store_id 归 organization；租户不等于法人。服务端根据可信域名映射+认证会话查租户，拒绝请求体覆盖。每租户连接池、最小权限独立角色，撤 PUBLIC CONNECT、跨库权限和继承；所有查询、缓存、任务、对象路径、幂等键均含租户。保留 identity.A、supply.A 等既有别名，不复制主数据。
逻辑供应能力查找：resolve(tenant,environment,capability,operation,config_revision)，返回已批准 adapter_id/version、endpoint_ref、credential_ref、merchant/store mapping、allowed_operations。优先扩展现有服务端配置加载器，后台仅可提交候选配置，由授权者批准原子激活；密钥从受控秘密存储取，不写Git/浏览器/日志。配置版本可回退、请求钉住原版本。读超时可限次重试；资金、核销未知结果先查原供应商，不自动换供应商重发。地址变化可配置；签名、字段/语义差异需要适配器升级，不允许把任意URL/脚本当代码执行。HTTPS、域名与路径白名单、DNS重绑定/私网地址防护、禁止任意重定向、超时、最小权限、脱敏日志；故障时仅批准的非敏感静态快照回退。
功能开关按tenant/store/role，默认OFF；服务端同步拦截，不只隐藏按钮。紧急关闭阻止新操作但保留查询、退款和对账。G0/G1是生产硬门槛，不阻断隔离开发。
## 验收
双租户同ID不串库，跨域名/会话/缓存/任务/文件/回调拒绝；配置坏值/私网/未知适配器拒绝；旧供应商未知付款不得重发；开关关闭仍可完成合法售后。两租户仅合成库；无生产DDL。配置切回上一版本，不改变历史交易绑定。

## 全员通用执行指令
只领取本工作包；从集成人发布的同一不可变集成基线创建独立 Git worktree/分支，使用合成数据、隔离数据库与测试替身。先比对现有模块是否已有可复用函数，禁止重写。可在未获供应商授权时写契约测试、离线实现；不得声称真实接通。不得读取或修改其他Agent工作区、运行目录、共享数据库、端口、systemd、Nginx或生产资料。共享入口、数据字典、迁移登记、注册表、POS文件由集成人或既有POS负责人唯一写入；提交最小补丁请求。契约变更必须先冻结新版本并通知依赖方，不得单方面改变语义。
交付：变更文件清单、复用证据、业务流程及算法、测试结果（PASS/FAIL/MOCK_ONLY/NOT_RUN）、契约版本、迁移候选、回退、未解阻断、PR/SHA；不做部署。缺少真实授权时标 BLOCKED_LIVE，其他合成任务继续。禁用模块不得删除历史资产或重试未知资金交易。任何真实数据、密钥、商户凭证、私人经营政策不得提交Git。
