# HQ-CATALOG-01 / #63 候选交接
独立基线 2052ef51f011be3c5898d816932d8982f420b752（PR #40）；选取 PR #42 的只读校验器和单元测试，不合并整条旧分支。沿用 identity.A、统一会话、CSRF、HQ 工作台和既有 catalog PG 读取。新页面 /hq/catalog；接口 /api/v1/hq/catalog/*。无新端口、数据库、登录或POS写入者。
 
## 隔离启用（不部署正式）
在 #58 唯一集成工作树由 C 确认运行基线后，逐文件核对增量，严禁覆盖本地更新。仅现有 isolated identity 服务配置 BSV_HQ_CATALOG_ENABLE=1、BSV_HQ_CATALOG_LEGAL_ENTITY_ID（已核验法人）、BSV_IMPORT_ROOT（已有私有目录，同服务账号0700）、BSV_CATALOG_DIR（现有私有原始版本目录）、BSV_CATALOG_READ_SOURCE=postgres、BSV_APP_ENV=isolated，以及现有受限同库 PG reader BSV_DB_URL（核实不会改变 identity.A 数据源；不匹配则先解决连接别名，不改原身份库）。BSV_HQ_CATALOG_SCANNER 是既有受审的本地扫描器绝对路径，参数为文件路径，0表示干净，任何其他状态拒绝；不设置假扫描器。现有 ingress 4MiB 上限不扩大全站限制。通过原身份授权工作流分别授予 hq.catalog.read/draft/review（HQ、同法人、双人审批，不从地图权限派生）。本分支无预设授权。真实生产模式仍拒绝。
 
## 已编写
- 工作台和总部入口、移动端页面、C/P/M/K/R/Q/T 搜索分页、有限安全字段展示；原始Excel与PG活动SHA核验。
- Excel安全扫描与 #42 差异预览，候选同SHA幂等入队；网页新增、修改、退役、历史恢复申请使用同一私有草稿队列。T在页面只读；未分配永久ID，不猜号；草稿不是业务主数据。
- 两位不同TR审核，审核不发布、审计保留、活动版本变化拒绝审核；未配置或无权限拒绝。正式销售和历史交易不修改。
 
## 不完整/硬阻断
- Excel -> WorkBuddy规范包转换及完整字段字典、K槽位/NPS/公式缓存/全量引用校验、现有永久ID分配器及历史ID不重用核验、行级草稿应用到统一候选版本、PG事务签名/审批桥、恢复目标校验及激活、POS投影验证尚未完成；现有 importer 限制隔离且要求OS签名，严禁伪造或改成直接写SQL。草稿批准只记 REVIEWED_NOT_PUBLISHED，不是发布权限。
- 真实目录及身份/主机未核验。新代码与现场集成测试需执行。不要把本 PR 当生产可用。
 
## 腾讯云增量执行
1. 读取 #63、PR #40/#42、#44/#58；本次独立候选不阻断M1。独立worktree，核对运行SHA及备份；接入现有身份服务和路由，不新增服务。运行 bash tests/bsv1/check.sh、identity和internal-stage回归，检查浏览器未授权拒绝、草稿/同人拒绝/异人审核、重复Excel、不匹配SHA、扫描失败、实际目录读。
2. 结合主机上已批准 WorkBuddy 生成器和字段字典实现原始Excel及网页草稿到同一标准包，保留公式原文/缓存、K子区/引用/列，固定ID从历史账本分配，缺行默认退役申请。复用 bsv_catalog_import.py 的 _verified_package/import_package/activate_source_revision，建立经独立审查的身份双人审批到签名桥与受控执行账号。绝不能为了界面显示成功而跳过审批或放行可售。通过现有PG事务及审批激活、恢复和POS投影验收。不能确认条件时冻结阻断，禁止改正式库。
3. 交付实际候选SHA、浏览器验证、回退步骤、未完成项；生产启用独立批准。不得改订单、地图、收款、配送等并行模块；不泄露私有资料。
