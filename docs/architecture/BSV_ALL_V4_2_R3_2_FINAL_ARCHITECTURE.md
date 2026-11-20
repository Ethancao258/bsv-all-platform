# BSV ALL V4.2｜R3.2 双架构最终设计母版

> **版本** R3.2-FINAL-DESIGN / 2026-11-21。状态：`DESIGN_FROZEN_FOR_USER_REVIEW`；无新增程序、无DB迁移、无云服务器变更、生产NO_GO。本文供经营负责人审阅并供后续Codex按批次使用，**不是**授权直接启动Codex或上线。十专业审查为依据真实标准的模拟交叉评审，**没有十位真人专家参加或签字**。

依据：`docs/governance/BSV-GOV-ARCH-2026-005_V5.0_20261118.md`、`AGENTS.md`、`config/data-ownership.json`、`config/domain-registry.json`、`config/change-routing.json`、`docs/ops/CODEX_WORKFLOW.md`、GitHub Issue #14中的R3全部业务规则。冲突时以已批准的经营规则和真实源码/主数据为准，需ADR变更，不让Codex擅自推断。本文件是**两套架构之间的唯一说明**，不是另一个权威数据注册表。

## A. 已查验事实、重要冲突与限制

- 本版只读审计的V4.1 Git SHA：`c51b58d67dabae53afcdf9851a80cdc93d4200f6`，PR #12 OPEN。经营负责人提供的腾讯云日志出现`V4_STAGING_ACCEPTED`；这是**用户主机日志证据**，并非此次专家审查直接SSH或验证生产数据。
- 代码仓库已有20个逻辑领域（`config/domain-registry.json`）、6类应用（`config/app-registry.json`）、11个变更模块（`config/change-routing.json`）、32条用例（`config/use-case-registry.json`）；32条仍全写`DESIGN_ONLY`，但V4.1部分已有隔离代码与主机测试，属于**状态目录滞后**，不能统一标完成。
- 已有V4.1运行服务：隔离入口18760、身份/学院18761、POS18762、供货18763、隔离PG18764，原8765/8767保留。当前`config/resource-registry.json`仍写较早的部署SHA及`v4_1_host_result=HOST_NOT_RUN`；G0必须用有来源、时间、SHA的事实修正，保留旧证据。
- `services/api/identity/api.py`已有TR/EMP/BM、任职、资格、授权、撤权和学院API；`services/api/bsv1/app.py`以SQLite保存历史员工/座位/订单/出品；`services/api/supply/`已有A–G接口和隔离演示，生产D/E权威事务仍BLOCKED。**不能因此假设同一笔业务已经在一个中央数据库原子完成**。
- `services/api/identity/academy_policy.py`只开放BSVS/BSVT；`services/api/bsv1/store_layouts/stores.json`有BSVM/BSVS/BSVT/BSVF四个规范码；企业经营描述五店。第五经营点的`store_id`必须核实正式组织记录，不能随意猜号或自动发店级资格。
- `platform/lighthouse/internal-stage/ingress.py`当前默认把多数`/api/v1/*`请求送身份API、其他送POS；且`/craft/`原设计对应公开精酿页面，当前404。**新员工调酒引导必须使用独立受保护路径（建议`/work/craft`），公开`/craft/`是否恢复按原公开功能另行确认。**
- CloudBase上海现有产品表、Lighthouse北京隔离PG、POS SQLite属于不同环境与事实来源。CloudBase实际Schema/ACL/RLS/官方迁移记录尚未在本次审计实时SQL核对，不能擅自把正式主库搬到Lighthouse或开正式写入。

## B. 十专业联合决议：先接口，再功能

| 专业视角 | 独立发现 | 共同决议 |
| --- | --- | --- |
| 企业管理 | BSV1/2/3容易误变成三套软件 | 只按经营责任划分，不按圈层复制主数据 |
| 连锁餐饮运营 | 中央供货故障会影响基础经营 | BSV1保留合规基础采购/制作/服务路径，安全失败则停卖 |
| 组织行为与HR | 主店、支援意愿、培训、授权、班次、到岗混淆 | 六类关系分立且分别追溯真实事实，收公告不授岗 |
| 心理与认知 | 公告和考试可能淹没员工 | 只有相关任务优先首屏，普通公告不一律强制考核 |
| 服务设计 | 同一动作各页面入口割裂 | 员工、顾客、BM只是同一业务不同授权视图 |
| 视觉设计/HCI | 各应用重复造导航/弹窗/状态 | 统一设计Tokens、共享交互组件、手机键盘和减动画 |
| 身份与安全 | 手机变号、共享平板和BM越权 | person_id稳定、TR不改、手机号可变、实时鉴权与撤权审计 |
| 数据/DDD | 表、ID、事件与旧系统重叠 | 每事实唯一owner；历史码显式映射；接口和状态版本化 |
| 支付与财务 | 储值款与销售收入、加盟兑付混同 | 预收资金负债、订单/资金/权益分开；模拟与正式硬隔离 |
| SRE与合规 | 20领域若拆20进程会造成维护成本 | 保留现有服务、集中观测、异地恢复演练、批次食品安全锁止 |

**最终技术决定**：`单仓库 + 20个逻辑领域 + 当前已验收服务边界 + 一套认证与受控消息协议 + 唯一领域写入者 + 适配器渐进整合`。不强行实现20个微服务/20个数据库，也不强制将现有身份、POS、供货合并为巨型进程。任何物理拆分需要独立ADR、测得资源及收益、故障隔离与回退论证。

## C. 架构一：业务链与责任

经营圈层按企业母版：**BSV1**包含产品研发、招聘培训、门店、基础营销、采购、出品、支付、日常财务与IT；**BSV2**包含总部增长、中央供货、独立督查、外部合作/系统商业化；**BSV3**为资本治理。它们不是三种软件版本。

~~~mermaid
flowchart LR
    A[统一人员与门店] --> B[任职培训排班]
    B --> C[打卡开店找物]
    D[产品配方与供货] --> E[POS订单和调酒]
    C --> E
    E --> F[支付核验顾客权益]
    F --> G[日结SDF]
    E --> H[异常质量督查]
    H --> I[纠偏与更新课程]
    G --> J[增长合作资本决策]
    I --> B
~~~

| 端到端业务链 | 发起/负责 | 不可替代的事实源 | 跨模块交接/异常 |
| --- | --- | --- | --- |
| 员工入职→资格→当班 | BM/人事 | workforce.TR/主店/班次/真实考勤；learning考试/实操；identity_access授权 | 资格校验后POS才准操作，异常入service_ops |
| 本店公告→学习→岗位更新 | BM/产品负责人 | knowledge公告/版本/读确认；learning考核 | 收件人由主店/资格/实际班次推导，公告不直接修改授权 |
| 产品→点单→制作→送达 | 产品/门店负责人 | catalog商品/配方版本；commerce订单；service_ops出品 | inventory只按有证据出品/批次记账 |
| 采购→预调→配送→库存→安全 | 门店/中央生产/独立督查 | procurement供应商/采购，production批次与配送，inventory流水，quality复核 | 批次停售影响所有有关产品/门店，中央中断不删除基础路径 |
| 顾客→会员→存酒→支付→通知 | 客服/收银/财务 | customer会员/隐私；实物寄存唯一owner待登记；payments账本；commerce订单 | 跨店权限+发卡主体核验，消费通知失败不改支付事实 |
| 日结→营销/纠纷→财务/资本 | 经营/财务/营销 | operating_finance已核验结果、marketing活动、capital投资决定、service_ops统一incident | 禁把充值算收入、不能从测算利润直接推可投资现金 |

每条业务流程须有：唯一发起命令、主责岗位、业务事实owner、服务端授权、必要的证据、成功与不确定回执、补救/人工介入和责任人。**页面是一种视图，不是另外一种事实源。**

## D. 架构二：代码、服务、数据、API

~~~mermaid
flowchart TB
    UI[六类页面 Apps] --> G[统一安全入口 Ingress]
    G --> ID[现有身份+学院 API]
    G --> POS[现有门店POS API]
    G --> SUP[现有供货+督查 API]
    G --> EXT[按需新增领域应用服务]
    ID --> D[20逻辑领域Domain Contracts]
    POS --> D
    SUP --> D
    EXT --> D
    D --> INT[适配器: CloudBase旧SQLite收钱吧短信HPRT企微]
    D --> EV[本域Outbox+统一事件信封及投递器]
~~~

### D1. 层级及禁止关系

1. **apps**（`apps/staff-center`、`apps/store-console`、`apps/hq-console`、`apps/guest-web`、`apps/inspector-console`、`apps/partner-portal`）：复用导航/AppShell、状态灯、表单、选人群/错误反馈，不做服务端权威鉴权、不直接连接PG。规划页不等于已运行。
2. **ingress**：显式注册所有路径及目标服务，区分匿名公开菜单、内部员工调酒、顾客会员和总部。未知路径404，不再默认回落不相关服务；携带request_id、统一Cookie/CSRF和审查限额。**网关不写业务表**。
3. **services/api**：在现有`identity`、`bsv1`、`supply`入口实现服务端业务命令，调用所属`domains/*`规则。新增域逻辑优先放现有进程合适的模块，不为每个模块造新进程。进程分离需明确健康/容量/安全ADR。
4. **domains**：现有20领域是稳定逻辑边界、拥有唯一实体及操作规则；同进程可共享事务，**跨进程/跨DB不可伪造ACID**。不同服务不能绕过owner写对方表。
5. **contracts**：`command/event/query/error`契约，包含稳定ID、法人与店级scope、版本、actor、idempotency_key、超时与不确定状态。接口不允许由UI臆造已完成。
6. **integrations**：连接CloudBase、收钱吧、微信/企业微信、SMS、打印机、旧POS SQLite等；统一适配，正式不可用时标记`BLOCKED/MOCK_ONLY`，不能静默选择不可信备用库。
7. **config / platform**：逻辑source namespace→运行时私有端点/凭据，Git不存真实token。`identity.A`与`supply.A`必须区分。CloudBase到Lighthouse物理归属仍需待批ADR。现有服务与旧端口保持。

### D2. 公司唯一身份和员工门店关系

一个`identity_access.person_id`（需G0确认新增owner）对应可换绑的认证subject/手机号；已批准员工引用永久`workforce.tr_code`，派生EMP/BM共享后缀；顾客引用独立`customer.customer_id`。同一自然人经可信核验可跨角色切换，**不凭同名同手机自动合并，更不把顾客新增为TR员工**。

六类门店关系：`PRIMARY_HOME`归workforce、`WILLING_TO_SUPPORT`归workforce、`TRAINED_FOR_STORE`由learning派生、`GRANTED_FOR_STORE`由identity_access派生、`SCHEDULED_FOR_STORE`由workforce批准排班派生、`ACTUAL_ATTENDANCE`由服务器真实考勤事件派生。每类分别带有效期和原因；实际到场不代表已经获得配方/POS资格；安全公告覆盖与保密信息可读性分别判定。

### D3. 最重要的兼容约束

- `tr_code`、`employee_id`、`customer_id`、`store_id`、`product_id`、`bundle_id`、`order_id`、`batch_id`等现有规范ID不重新发码。POS旧员工ID用受限`legacy_aliases`及法人/来源scope明确映射。
- 现有`data-ownership.json`已将`receipt_id`归采购收货，**打卡凭证只能用另一个有唯一owner的`clock_receipt_id`，不能抢这个ID**；座位`seat_id`、钱包`wallet_id`、公告ID及存酒`custody_item_id`等先核查现有字段，确有缺口才通过ADR加owner。
- 禁让客用`/cocktail/`注入工作台返回；建议把员工制作入口设为`/work/craft`，公开`/craft/`仍需确认其历史精酿用途，避免URL冲突。
- 现有POS SQLite业务事实在迁移批准前保留其旧owner/来源身份；不能前端同时写POS SQLite和另一个“中央订单”表。迁移时明确`expand → dual-read compare（非双主写）→ single-writer cutover → retire`及恢复。
- `knowledge`保存公告内容和版本，`workforce/learning`决定受众关系，`identity_access`决定是否能看敏感正文；外部通知只是渠道，不是主档或考试通过的证明。
- 本域Outbox由业务事实同一物理DB事务写入；多个DB允许分别有本地outbox，但**只有一套消息信封/投递协议和幂等处理器**。消费者去重，跨库失败可查单/补偿，不假称exactly-once。
- 正式收钱吧储值额外0.68%仅为用户反映未核对合同，真钱、现金充值、团购真实核销、CloudBase生产D/E及正式短信都继续NO_GO。

## E. 八个必须跨模块通过的业务旅程

| 旅程编号 | 起点→实际写入→受控下一步 | 失效反例 |
| --- | --- | --- |
| J1员工入职 | BM代理登记→两人批准发TR→EMP/主店/学院资格→授权班次 | 同一BM不可自批；顾客不能直接获TR |
| J2当班打卡 | 工作台→服务器CLOCK_IN→可拍照大字时间凭证→企微群人工送照→开店清单 | 未成功写库不能显示“已打卡”，群内发送不得假成功 |
| J3计划下班 | 班次到点锁正常延班→禁止员工自己改计划→未完成订单交接→实际CLOCK_OUT可如实记录 | 不得伪造到点即实际下班，也不能抹真实晚退工时 |
| J4公告培训 | 选门店/人群→去重公告→员工已读/确认→岗位必要课程考试 | 仅愿支援不获POS或机密配方；多店一人只发一次 |
| J5调酒 | 订单已批准SKU版本→员工`/work/craft`查询配方与本店位置→出品→库存事务 | 无资格、错店、配方过期/批次QUARANTINED拒绝 |
| J6中央供货 | 批次与配送→发10收9→在途1→督查复核→安全停售通知 | 重复签收不能重复入库；违规复核不通过 |
| J7钱包/存酒 | 顾客验证→可信支付Mock/现金双核验→payments账本→存酒/消费记录→站内+验证邮箱通知 | 同交易重放不双记；通知失败不回滚已入账，跨法人真实兑付不放行 |
| J8异常/恢复 | 订单、库存、员工、资金等异常→唯一incident_id→责任人/限期/证据→独立复核→关闭 | 前端不能删除原记录、自己复核自己；备份有文件不等于恢复成功 |

## F. 设计与工程边界：十位专业视角的共同门槛

**安全**：每次检查subject/action/resource/store/role/credential/shift/device/expiry；紧急权限暂停允许一名有授权BM即时停权，但必填理由分类、备注选填，通知其他BM并留不可变审计；恢复敏感权限需独立审批。用户手册版本确认、敏感字段/私钥最小化、共享平板重新识别本人、正式资金高风险重新认证。

**UX**：统一页头“工作台/上一页/其他授权工作”；首屏只显示最重要下一步；管理人事待审批先于长权限列表；公告按门店卡片一屏发布、动态收件人数去重，减动画及触屏；公开菜单默认没有员工技术信息；技术`MOCK_ONLY`说明在受控交易与运维界面透明展示。

**可恢复性**：4vCPU/4GB/40GB现有资源必须实测CPU、RSS、连接数、p95与备份空间，不准先声称够五店高峰。独立云加密+Windows本地副本，RTO目标4h、非资金RPO15分钟，必须在干净隔离环境重建并核对钱包账本/媒体/配置/迁移。自动恢复优先受控重启无状态组件，禁止自动重启整机/数据库造成重启风暴。

**第三方和合规**：正式会员短信、企业微信群送达API、收钱吧储值余额迁移、真实钱包、合作商户之间兑付及食品安全实际许可证均需要真实合同/凭据；不能以模拟测试代替现实许可。全线上版本断网时资金/身份/库存写入fail closed，离线版本以后独立研发。

## G. Codex开始前的G0架构闸门

**G0只盘点/出规范和机器契约，未获另行批准不得修改业务代码、迁移数据库、支付、发送短信、部署。**

G0-1：32个use case逐条标注四维状态`code_status / ci_status / host_status / production_status`及对应证据SHA、来源和时间；更新`config/resource-registry.json`的过时状态，但不能将用户终端回执当作程序直接SSH。

G0-2：完成“业务→domain→唯一writer→现有表或UNKNOWN→API与事件→前端→测试→风险级别”的机器矩阵；新增`person_id/seat_id/clock_receipt_id/announcement_id/wallet_id/custody_item_id`前查原表与schema。

G0-3：完成真实Ingress路由清单，明确`/api/v1/*`的归属、公共`/craft`与员工`/work/craft`、鉴权/CSRF/静态资源及故障路径；取消隐式兜底设计，未注册返回404。

G0-4：完成隔离PG/SQLite/CloudBase产品表、旧码、主备读源、官方迁移和数据回退的**真实来源矩阵**；没有正式CloudBase访问时仅标UNKNOWN而不伪造结论。

G0-5：权限/二人审批/共享设备矩阵与UI任务基线；跨模块依赖不能产生无界循环：POS有权请求身份实时决策，身份服务不应通过POS查询再决定身份发码。

G0-6：静态自动门禁：重复对象owner为零、未注册新路由为零、无法证明安全授权的越权交叉写入为零；有明确升级、回滚、资源占用和失败停止点。当前**此设计文件并未实际运行G0测试**。

G0具备证据后，按原R3七个小批次A-G执行：A统一入口/身份契约/审计与UI；B人事/公告/考勤；C POS/新网页调酒/找东西/交接；D中央D/E与食品安全；E顾客/会员/存酒/团购Mock；F钱包Mock/财务/通知/营销合作；G实机健康监控/灾备/跨域E2E。**G0后每次Codex只接收本批最小路径、权威对象、输入输出、正反测试和STOP条件，不能再重读所有历史聊天。**

### 本版尚未消除的剩余风险（必须明示）
CloudBase真实产品表与权限未直接验证；第五门店规范ID未知；实际收钱吧API和五店商户结算账户待合同核对；现有4GB主机真实高峰容量未实测；短信服务商模板未通过审批；正式储值与跨店资金规则须合规审查；用户端交互尚未实机测试；R3.2整套系统无完成代码和E2E证据。

**裁决：设计可用于负责人审核，审核通过后先做G0取证，不等于能无漏洞直接交付正式生产。**

参考：Martin Fowler的MonolithFirst/BoundedContext，C4 Model，Microsoft Strangler Fig，AWS Transactional Outbox，Google SRE SLI/SLO，NIST SP800-53。
