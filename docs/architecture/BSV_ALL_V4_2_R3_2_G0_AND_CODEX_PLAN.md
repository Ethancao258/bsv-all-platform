# BSV ALL V4.2 R3.2｜G0 取证与 Codex 批次执行契约

**状态：设计评审用，不是施工许可。** 继承 [R3.2双架构母版](./BSV_ALL_V4_2_R3_2_FINAL_ARCHITECTURE.md)；逐条用例依 [32条机器映射](../../contracts/v4-2/R3_2_USE_CASE_INTEGRATION_MAP.json)。原R3七张A—G小执行卡保留，**本文件约束其先后顺序和跨模块边界**，不新造七个重复Issue。全部以GitHub Issue #14为统一任务来源。工程基线V4.1 commit `c51b58d67dabae53afcdf9851a80cdc93d4200f6`。设计分支不是部署分支；用户审阅及另行授权后再启动Codex。

## G0：前置六项取证（必须独立出结果）

| G0 | 必查现有材料 | 交付证据及机器检查 | 禁止 |
| --- | --- | --- | --- |
| G0-01真实程序现状 | `AGENTS.md`、`CURRENT_STATE.md`、`config/resource-registry.json`、`config/use-case-registry.json`、V4.1主机回执 | 32用例多维状态`CODE/CI/HOST/DATA`，每条关联SHA、测试/主机报告、时间和来源；修正过期的HOST_NOT_RUN | 代码文件存在不等于完整功能，用户journal不等于此工具直接SSH |
| G0-02主数据与稳定ID | `config/data-ownership.json`、`domain-registry.json`、`contracts/database/BASELINE.md`、真实可授权的只读schema查询 | 每个当前/拟议ID有唯一owner、实际字段或UNKNOWN、历史别名和迁移/保留方案 | 别造person/store/order/customer/seat/receipt重复主表 |
| G0-03代码与HTTP入口 | `platform/lighthouse/internal-stage/ingress.py`、`identity/api.py`、`bsv1/app.py`、`supply/main.py`、`change-routing.json` | 真实路由与HTTP method映射，敏感操作服务端鉴权；`/craft`公开与`/work/craft`内部不冲突；明确GET/POST/PUT/PATCH/DELETE的允许方法和CSRF | 不保留`/api/v1/*`全部默认送identity的隐性分派或未知路由回退POS |
| G0-04数据源/迁移与外部 | CloudBase已有10产品表的真实schema/ACL/RLS/迁移账本（若获授权）；隔离PG、POS SQLite、供货A–G、收钱吧/短信合同状态 | source→事实owner→读写者→环境/授权→契约版本→备份点→回退；UNKNOWN与BLOCKED分别标注 | 不能私自迁真实CloudBase、双写新旧订单、开真资金/短信 |
| G0-05业务/权限/UX | 既有学院策略、排班和设备、POS令牌、店级门店名册、管理后台截图与既有R3 | 授权矩阵、人事/公告/考勤/订单/钱包八条跨模块旅程的状态机与错误语义，界面任务基线 | 不把通知收件当上岗许可、不把屏幕计划下班当真实离岗 |
| G0-06发布/灾备与容量 | `docs/ops/CODEX_WORKFLOW.md`、`platform/lighthouse/internal-stage`、主机容量监控/实际文件 | release manifest要求、可验证CI/迁移回滚/灾备计划、资源测量与止损门禁 | 不宣称4GB足够生产高峰，不因前台job超时就重复执行 |

**G0完成可机器证明的条件**：同一个对象没有两个权威可写owner；32/32用例可追溯但各维状态不虚报；11条旧模块路由都有可核实代码入口；六个页面角色可区分；旧账户/TR/门店映射没有强制重编码；未知第五门店标UNKNOWN；不修改正式库、不直接调用真实商户接口。无法取证的正式集成只标BLOCKED，不阻止脱敏隔离Mock的功能实现。

## 八个共享技术契约（新业务都调用，禁止重复造）

| 契约名称 | 唯一主责/现有载体 | 供谁调用 | 失败处理 |
| --- | --- | --- | --- |
| IdentityContract | `identity_access` + 现有`services/api/identity` | 所有员工/顾客入口 | auth失效直接401，不用旧快照代签 |
| StoreAndScopeContract | `organization`门店，`workforce`主店/意愿，`learning`资格/班次，`identity_access`Grant | POS、公告、供货、学院、管理台 | 无主店/资格记录=UNKNOWN或403，不允许凭意愿授权 |
| CatalogVersionContract | `catalog`已有产品/菜单投影 | POS、调酒、供货、营销、客用菜单 | 无批准配方不能调制或核价，旧订单保存原快照 |
| CommandAuditContract | 业务owner本地事务+`event_audit`统一封装 | 所有BM和总部管理表单 | 必填风险原因与可选备注分开，重复请求查原结果 |
| EventOutboxContract | 每个事务数据库本地outbox + 同一事件协议/dispatcher | 公告、紧急撤权、顾客消费提醒、库存事件 | at-least-once＋消费端去重，网络失败排队，不假报已送达 |
| TaskIncidentContract | `service_ops.incident_id/task_id` | 员工、店长、总部、督查、客服 | 每次出错有owner、严重性、处理期限与补偿动作 |
| PaymentAndWalletContract | `payments`资金事实+`commerce`订单事实 | POS、会员、财务、客用钱包 | 外部可信查单/现金双人核验；未证实付款=UNKNOWN；不双记 |
| ReleaseAndRecoveryContract | `platform`发布器+版本化schema/对象/备份 | Codex、运营、开发、审计 | SHA不对/迁移失败/恢复未验则拒绝上线；数据不可只靠symlink回滚 |

**谨慎**：`EventOutboxContract`是统一事件协议，不是“在中央新库放一张outbox就能覆盖旧SQLite与PG所有事务”。本域事实和本地outbox必须物理同事务；跨DB只能已定义重试/补偿。`TaskIncidentContract`是全公司一个逻辑incident_id，不代表所有异常都允许普通员工查看私人细节。

## A—G 七批的严格任务输入（只写差异，不读完整聊天）

### A｜身份与共同底座
**允许重点路径**：`config/*`（注册表与路由）、`contracts/*`（受控API/事件）、`services/api/identity/*`、`domains/identity_access/*`、`apps/staff-center/identity/*`、`apps/hq-console/identity/*`、`platform/lighthouse/internal-stage/ingress.py`及对应tests。**入口**：G0证明当前实体及端点。**输出**：person→TR与customer可验证link契约，稳定会话/手机号Mock边界，权限/设备切换、统一共享UI/AppShell、应用URL/前后端路由显式化、审计操作备注与事件信封；不能在A同时造完钱包/供货。**验收**：客户不能读人事，员工转店权限动态拒绝；旧TR/EMP/BM不变；7屏可返回；旧路由与公众菜单不泄漏机密；任何原有CI失败则停止。

### B｜员工关系、考勤、学院更新与公告
**重点路径**：`domains/workforce/*`、`domains/learning/*`、`domains/knowledge/*`、`services/api/identity/*`、`apps/staff-center/*`、`apps/hq-console/identity/*`及隔离迁移/测试。**依赖**：A的auth/StoreAndScope/CommandAudit/EventOutbox。**输出**：主店唯一有效+可支援N店、与当前已授权/已资格/已排班/真实到岗分离；服务端CLOCK_IN/CLOCK_OUT+拍照大号时间凭证、计划到点锁定但实际离岗可记；BM人事双审/24h离职复核/单人紧急停权+通知；门店卡片精准公告、去重收件、已读/确认/考试/送达四种事实；文森特学院考试版本与受影响岗位授权联动。**验收**：同人两店公告去重，愿意支援不获POS、实际未经批准上班事实仍可记录，无法自己复权，不能用公告发授岗权。

### C｜门店位置、POS与真正可用的内部网页调酒引导
**重点路径**：`services/api/bsv1/*`、`apps/store-console/bsv1/*`、`domains/commerce/*`、`domains/service_ops/*`、`domains/organization/*`、`domains/catalog/*`及对应tests。**依赖**：B的资格/打卡与A的routing。**输出**：店内位置store→area→fixture→shelf→slot、图片版本和开闭店清单；`/work/craft`读取订单的批准配方版本、同店库位/使用步骤及出品任务；共享平板真实operator识别；下班未完成订单转合格接班人，没有接班人生成incident。**验收**：旧SQLite稳定ID和order_id不变；客用公开路由无调酒配方；同订单不出品两次；异常不“成功”。

### D｜供应链与安全督查
**重点路径**：`services/api/supply/*`、`domains/production/*`、`domains/inventory/*`、`domains/quality/*`、`apps/hq-console/supply/*`、`integrations/devices/*`、`tests/supply/*`。**依赖**：A的source/审计契约，C的物料/库位ID。**输出**：隔离PG D/E权威事务、统一批次与标签HPRT T260L 203dpi 50x40mm、发货签收盘点/错批限制/停售召回/独立复核；安全公告走B接口。**验收**：发10收9在途1、重复扫码不重复扣库、错店拒绝、停用批次不能出品、真实CloudBase D/E写入仍BLOCKED。

### E｜顾客、存酒与团购券
**重点路径**：`domains/customer/*`、`domains/commerce/*`、`domains/service_ops/*`、`apps/guest-web/*`、相关适配器及测试。**依赖**：A统一person/cust与C同一订单主码。**输出**：顾客ID/已验证联系方式/跨店会员权益、独立实物存酒和赠送权益、存取事件及到期待处理、团购查券/映射/Mock核销到一份订单、客诉与纠纷incident。**验收**：手机号相同不自动合并、合作方不能全库读会员、存酒并发领取不负数、券重复不多次下单、真实核销NO_GO。

### F｜资金模拟、消息、经营与合作
**重点路径**：`domains/payments/*`、`domains/operating_finance/*`、`domains/marketing/*`、`domains/partnership/*`、`services/api/*`既有入口、受控第三方adapter与测试。**依赖**：A事件/审计、C订单、E顾客；只消费B公告通用投递协议不重新发明消息平台。**输出**：多渠道Mock付款/现金双人复核→隔离双式钱包账本→消费或退款→站内+已验证邮箱通知（SMS仅Mock）→财务日结/SDF与合作分成/营销任务。**验收**：重复回调一次记账、跨数据库不能声称一笔ACID、付款未证实不能加余额、通知失败可重试但不重做交易、真实储值及跨主体资金NO_GO。

### G｜真正的运维、恢复和整体验收
**重点路径**：`platform/lighthouse/*`、`docs/ops/*`、`tests/*`、`config/resource-registry.json`及必要监控契约。**依赖**：A—F通过各自CI；主机只有明确受控发布批准才能实际部署。**输出**：核心业务合成探针、红黄绿灰状态/上次检测时间、独立外部故障告警、单个无状态服务限流重启、云端加密+本地可恢复备份、真实隔离还原与Windows浏览器人工流程证据。**验收**：过去R3 T01—T35全部适用通过+本文J1—J8跨域错误测试，RTO4h/RPO15min仅在真实恢复后可标达标，禁止自动整机重启。

## 实际交付状态必须显式报告
所有批次PR或Issue回复采用同一结构：
- `baseSHA`、`newSHA`、`target_environment`、`allowed_paths`、`schema_revision`。
- `reuse_existing_modules`（列真正复用的对象及依据）、`new_objects_and_why`、`contracts_changed`、`migration_strategy`。
- `CI_PASS/BLOCKED/NOT_RUN`，`HOST_VERIFIED/NOT_RUN`，`MOCK_ONLY`与生产资金/真实员工保护。
- 权限正反例、幂等/并发/跨库失败测试、回滚验证与当前唯一下一步。
- **STOP**：发现唯一主数据不明、旧TR/订单/门店冲突、要求真实凭据、未批准云DDL、数据库不可恢复、Codex要绕过权限、CI失败或无法确认baseSHA。

## 设计验收不变量（任何一项违背即不能“可以编码”）
1. 永久TR/EMP/BM编号及现有历史主码不改，不得自动为顾客生成TR。
2. 业务事实唯一writer、跨域合同版本清楚、所有系统均无第二份可写影子主库。
3. UI和gateway不凭客户端选择替服务端授权；共享平板操作必须是实际本人。
4. POS不会把员工支援意愿、公告收件或实际到场误认为店级资格。
5. 内部`/work/craft`、公众`/cocktail`和历史`/craft`互不抢占；未知API不会隐式代理错服务。
6. 每个已批准命令可追溯且超时UNKNOWN可查，重复请求不造成重复发码/订单/账本/库存。
7. 本地outbox与对应事实同事务，跨库消费者按event_id去重，不承诺全系统跨库原子性。
8. 顾客余额、赠送权益、实体存酒、实际收款和会计收入分别建证据与约束。
9. 班次到点锁定计划时间但不伪造实际签退；安全撤权与法定离职处理区分。
10. 食品安全批次隔离立刻阻断相关出品，不依赖普通公告已读。
11. 真实生产CloudBase/短信/支付/消费者PII/合作资金/公开域名未经专项批准不得开启。
12. 监控不仅看HTTP200；恢复报告真正证明完整数据、配置、版本和媒体能够重建。

**裁决：本文件是可审阅的施工合同，不是实际通过G0，也不证明“零漏洞”。经营负责人先审阅设计PR，批准后才允许执行G0取证，然后按A→G编程。**
