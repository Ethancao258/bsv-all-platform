# CX-WP-G｜美团抖音聚合验券 V1.2
状态：DESIGN_READY，非已实现、非已部署。阅读上版 ../cx-parallel-v1-1/README.md、CONTRACT.md、REGISTRY.json 及对应任务书；本版增量补充，冲突以本版设计建议为准，既有 AGENTS.md 与已批准正式契约优先。源码证据基线 2052ef51f011be3c5898d816932d8982f420b752；最新主机状态须由集成人复核。所有路径/表/字段为拟议映射，不是已创建对象。

业务范围：CX-22；旧模块编号与候选路径保留：integrations/marketplaces/cx/、services/api/customer_growth/cx_coupon/、apps/guest-web/cx-coupon/、tests/cx/G/。功能逐项索引见 FEATURES.md；新增操作见 OPERATIONS.json。

## 决策与证据
首选收钱吧智慧经营聚合查券；官方确认外部系统可对接多平台，必须授权门店。显式指定平台优于自动识别纯数字券码。美团是特殊入驻/应用授权路径，门店映射由收钱吧维护。直连可作为备用或后续替换；人工商家端始终可用但必须记录真实核销事实。未获实际报价和ISV/自助验券授权，最优成本待定。
## 实现顺序
G1 先申请开发应用、商户与逐店授权、试用测试券、报价和ISV再销售条款；并行设计标准adapter，不阻塞mock。G2 使用已核实接口：POST /open-api/v1/coupon/manual/query、manual/consume、cancel、consume/result、cancel/result；真实base URL/签名凭据经URA，不写业务代码。query参数 clientStoreSn/platform/couponCode/requestId（sqbStoreSn可选）；平台MEI_TUAN、DOU_YIN；字段详见官方最新文档，响应以授权联调为准。HMAC-SHA256按官方签名规范、禁止明文券码日志。G3 查询成功后保存offer快照、授权门店、内部SKU映射、查询时间及操作版本，用户确认实际套餐。官方文档规定查券后30分钟内核销；超过重新查券，24小时requestId幂等窗口不替代本地永久去重。G4 创建本地intent和唯一外部requestId后才核销，结果映射UNREDEEMED/PROCESSING/CONSUMED/CANCELLED/UNKNOWN。52005查券失效→重新查券并确认；52011处理中、超时→原requestId+原门店查result；52014无记录不是必然安全换供应商，核对平台终态。G5 成功时事务保存外部事实与outbox，通过F.external_fulfill幂等创建唯一POS订单，失败只重试补单；成功事实不重复核销。撤销独立requestId并遵循平台窗口，订单履约不可自动逆转。G6 每日核对平台核销、POS履约与结算（H）；异常人工处理，停用provider仍保留原供应商查询权限；切换仅适用未发送/终态确认未核销的操作，必要时重新查询和授权。
## 供应商评估
总成本 = 开发+接入费+维护+单量费用+人工异常工时+退出迁移；分别记录报价/授权/可用率/延迟/拒绝原因/对账完整。先用一个门店的小批量受控验收，成功后推广；对不支持用户自助/多企业商业授权的供应商不得宣称符合要求。
## 验收
未授权、错门店、已用券、纯数字、过期查询、24h后重试、超时/处理中、已核销POS失败、补单重复、撤销失败、供应商停用与跨租户。不得把券面值直接当实收。来源 https://doc.shouqianba.com/docs-for-smart/ （核销与开通具体URL见 SOURCES.md）。

## 给腾讯云执行Agent的合作规则
本设计是当前证据下的首选路径，不是不可修改的命令。你负责实机复核、提出更短/更优方案及实施。若发现既有实现可直接复用、平台接口变更或冲突，不重复研发：提交一条变更提议（原方案、实际代码/官方证据、替代方案、节省的变更/维护量、影响契约/数据/风险、测试与回退）。不改变外部契约、不降低安全、不改变产品目标且不抢其他路径的局部优化，可在所属分支直接实施并记录；共享契约、财务语义、数据归属、生产发布、法律约束变更由集成人/负责人审定，一次广播新版本。反例有证据则修正规范，不要求Agent重复完整需求研究。
开发仅限独立worktree、合成fixture、指定路径。禁止改运行release、共享数据库、公开路由、他组文件、实际支付/核销或生产DDL。依赖未就绪时只用统一fixture；不自行实现依赖方的业务逻辑。输出步骤逐项PASS/FAIL/MOCK_ONLY/NOT_RUN、代码位置、证据、PR/SHA、配置/迁移影响、回退及实机未决门槛。
