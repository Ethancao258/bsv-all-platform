# BSV ALL CX 并行研发规范 V1.1
状态：DESIGN_ONLY，未部署。只发布研究/契约，不包含执行代码、真实端点、凭据或原始服务器报告。
本规范与 AGENTS.md、config/change-routing.json、config/data-ownership.json、docs/architecture/BSV_ALL_DELIVERY_CONTROL_PLANE_V1.md、docs/ops/CODEX_WORKFLOW.md 同时适用；冲突由集成人登记ADR，不得自行覆盖。现有14根目录冻结。业务CX-01…32与工作包CX-WP-A…H分开。ACCWX是新别名，不假定已存在同名程序。
## 立项决策
八工作线并行开发、单一集成发布。最短路径不是八个Agent直接在同一运行目录操作。现有POS和会员代码优先复用；真实支付仍为独立门槛；租户路由与可换供应商为共用底座。先只读/合成切片、再真实授权验收。公开仓库不得上传内部报告、真实路径配置、凭据、客户资料或经营政策。
## 开工方式
集成人先核对最新部署源码与现有POS未提交增量；以共同 commit 创建集成分支并冻结契约（不得从旧main覆盖新修复）；A提供最小resolver与fixture合同，各Agent可同时开始独立模块/契约测试，A未合并前用同一fixture，不各造底座。每人独立 Git worktree 和分支 cx/agent-a…h（分支名须确认未占用），单一文件唯一写入者。禁止八套长期运行进程/八次部署。共享路由、app.py、ingress、迁移编号、注册表、发布脚本由集成人独占；POS负责人独占POS文件，F提交接口需求与最小补丁。每个Agent使用隔离测试数据库/临时目录，资源重任务最多1项同时在主机运行（初始保守操作约束，不是容量实测）；优先GitHub托管CI，主机只拉已批准SHA。GitHub权限不足时交脱敏patch给集成人，不将写权限私钥发给所有Agent。
## 路线与依赖
A共用契约；B客户身份，C公开菜单，D资产，E推荐，F订单桥，G核销，H资金。8条均可对冻结契约并行研发；真实联调依赖顺序 A→B/C→F→D/G/H→E，E计算可先用mock；H付款依赖E已核验结算，D商城权益依赖H已确认支付。相互依赖以operation/event区分，不形成循环启动依赖。F与POS既定热升级协调，POS负责人完成共享接入后才真正联调。实际主机及正式数据授权不是研发分支的前置条件。
## 最短发布序列
R0 契约+租户最小隔离，R1 C只读门户，R2 B会员及E/D基础权益，R3 F消费/服务，R4 G核销（或人工保底），R5 H真实支付/退款并完成D/E事实连接，R6 已批准储值、佣金发放、扩展商城及多企业试点。独立非依赖模块可提前发布；每次集成经已有发布控制面、CI、审批SHA、备份、业务验收及回切。合并不等于部署；停用不删数据。现有POS原进度不改变。G0/G1、公开入口TLS/备案及最小权限、真实数据、支付授权分别设生产门槛；不能公开内部隔离端口。对未核实存酒/计时，先经授权核对，禁止绕过原工具拒绝。
## 统一交付状态
DESIGN_READY→CONTRACT_READY→DEV_READY→PR_READY→CI_PASSED→INTEGRATED→STAGING_ACCEPTED；MOCK_ONLY/NOT_RUN/FAIL及BLOCKED_LIVE要单列；生产另批。集成人维护一次共享进度台账并分配迁移编号，Agents只报自身证据。非目标：新微服务集群、新消息中间件、重写POS、直接生产DDL、未经审批支付、未经许可发布。所有方案为设计决议，真实性以实际验证为准。
## 文件导航
- CONTRACT.md 统一契约；REGISTRY.json 机器可读工作包/编号/所有权提案
- CX-WP-A：租户、路由与功能开关 → A.md
- CX-WP-B：ACCWX与客户身份、会员、隐私 → B.md
- CX-WP-C：客用菜单、门店、推荐与门户 → C.md
- CX-WP-D：权益、存酒、积分、次卡与计时 → D.md
- CX-WP-E：推荐归因、佣金政策及服务关系 → E.md
- CX-WP-F：POS桥、到店会话、预约与服务任务 → F.md
- CX-WP-G：美团抖音聚合验券 → G.md
- CX-WP-H：消费支付退款、储值、佣金付款与商城 → H.md
## 外部证据与边界
Git worktree 官方文档 https://git-scm.com/docs/git-worktree ；PostgreSQL 角色 https://www.postgresql.org/docs/17/database-roles.html ；收钱吧 https://doc.shouqianba.com/docs-for-smart/ ；美团 https://developer.meituan.com/isv/daocan/ ；微信支付转账 https://pay.wechatpay.cn/doc/v3/merchant/4012715211 。第三方接入资格、报价、性能和真实生产路径仍待验，不宣称全球最优。以上按工程接口/依赖独立设计，不代表聘用外部专家。
