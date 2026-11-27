# SUP-59 中央生产、配送、标签、效期、库存与员工任务｜唯一开发接管手册

## 当前交付｜可运行隔离候选

以 [#52](https://github.com/Ethancao258/bsv-all-platform/issues/52) 的最终回执和 [PR #61](https://github.com/Ethancao258/bsv-all-platform/pull/61) 的对应提交为准。下文第 0–7 节保留原隔离规则交付及业务验收背景，历史“尚未实现”见本节更新。

| 位置 | 已交付 |
|---|---|
| `services/api/supply/central_routes.py`、`main.py`、`gateway.py` | 原供货进程内的授权路由，合成和 D 主源运行路径。D 业务回执需明确提交并返回原请求号 |
| `services/api/supply/central_transactions.py`、`demo.py` | 原演示账本 SQLite 内的生产计划、分装、逐件配送、隔离、开封、处置与打印历史。共用原配送清单、幂等和审计，旧写入路径拒绝受控包装配送单 |
| `services/api/supply/central_authority.py`、`contracts/supply/central-v1.md` | A 批准规则适配与 D PostgreSQL 幂等提交代码，现行 schema 对照及兼容迁移清单。需要接入 D 所有者真实事务与确认 A 映射 |
| `services/api/supply/central_print.py`、`integrations/devices/SUP_59_PRINT.md` | 使用既有 OpenCV 的包装 QR、50×40 mm 标签、到货与效期 A4，浏览器通过门店现有 T260L 系统驱动出纸。打印确认由员工单独操作 |
| `apps/hq-console/supply/central.js`、`index.html`、`app.js`、`style.css` | 现有总部、门店、督查共享页面中的中央生产和收货工作区，角色入口与供货服务耦合 |
| `contracts/supply/openapi.json`、`tests/supply/test_central_*.py`、`check.sh` | 追加路由契约、业务 HTTP、事务和权限反例、打印投影及扫码验证 |

### 本机或隔离工作树验收

在仓库根目录使用 Python 3.12 和 Node 22。使用现有供货环境或安装 `services/api/supply/requirements.lock`。
运行 `bash tests/supply/check.sh`，预期测试全绿并启动 Uvicorn 烟测。人工复核可在已授权的独立候选树运行：

```bash
export BSV_MODE=demo
export BSV_SUPPLY_STATE_DIR="$(mktemp -d)"
export BSV_SUPPLY_PORT=0
bash platform/lighthouse/supply/launch.sh
```

从进程输出读取实际 loopback 端口。本机打开 `/hq/supply`、`/store/supply`、`/inspector/supply`。服务器操作用现有获准的 SSH 隧道，有启用转发来源头的公网入口不适用于 demo。合成操作选择演示中央仓、BSVS、DEMO-P001、DEMO-RECIPE-1 及 DEMO-LOT-1。制作时间须早于提交，预计到货须在未来且先于合成死期。用 800mL 分装 450 与 350，先合格接收 450，再把 350 以温控异常隔离。同请求重放不增加库存，布局及标签确认另测。保持测试与现行统一隔离实例各自独立。

浏览器回归脚本为 `tests/ui/supply_central_browser.py`。安装 Playwright 并使用可用 Chromium 后运行 `python tests/ui/supply_central_browser.py http://127.0.0.1:<实际端口>`，可通过 `BSV_TEST_CHROMIUM` 指定可执行文件。脚本要求空白 demo 状态，会提交合成业务记录。预期打印预览与确认历史均可见；实际出纸另行验证。

### 腾讯云增量接管

1. 按 #44/#58 确认 C 的集成工作树、获准接管范围及发布基线。核对实际供货进程、D owner、schema 及注册表。审查后移植 #61 供应增量，禁止用参考分支覆盖共享运行树。
2. 按 `contracts/supply/central-v1.md` 核对已有 A、B、C、D、E。复用已核实的实体与权限。接入真实 D 命令和读投影，保留 authority helper 的顶层事务和显式回执；角色核对必须覆盖动作、对象、法人、仓库和目的店。已有等价路由只做映射。计划、包装、库存、打印及考勤中的未知字段应留有清晰阻断。
3. 先识别旧库存中已有获批效期及永久包装身份者，接入同一全店余额投影；缺少可信资料的存量列出待核或隔离，由店方实际核清。不可把历史件数猜成毫升或自动补有效期。将已确认班次的任务投影接入现有员工工作台，考勤、任务确认和报损/销毁仍分开。
4. 在独立候选中用合成 HTTP、真实浏览器和打印驱动验收；先执行逐件收货、重复重试、过期/隔离、历史库存、打印、任务及跨店拒绝。接入获批的 D 主源后才配置 `BSV_MODE=remote` 和 `BSV_SUP59_D_V1=1`。原 `internal-stage` 模式继续关闭新写入。校验 `/api/health` 与实际访问路径；健康可用不等于 D 权威数据核验。
5. 以现行 D 官方迁移计划生成精确 DDL。变更前保留版本、配置、受控加密备份与恢复演练记录；验收通过才接受集成候选。真实数据、主机、打印机与最终生产授权分别记录于 #52。
6. 回退先关闭候选开关并恢复前一实际服务版本和配置。已经提交的权威库存或生产事实须保全，使用现有 D 补偿流程；不得以回切源码替代数据修复。数据库回退使用已批准的恢复路径，在独立环境核对数量、审计和权限后再决定切换。

### 剩余实机证据

D 正式事务绑定和 schema、正式 A 规则版本、未映射历史库存、独立督查整改及真实班次事件、实体 T260L、服务器浏览器、现场备份恢复和发布。现有照片辅助仍只返回草稿，POS 扣库与外部 AI 直写不在本候选。没有生产数据库迁移或生产部署。

状态：ISOLATED_CANDIDATE / NO_SERVER_WRITE。经营负责人已要求开展研发；此分支从公开参考SHA 2052ef51f011be3c5898d816932d8982f420b752 派生，仅新增独立纯逻辑和测试，不改变当前运行路径；#44/#58 集成发布边界保持不变。不得直接部署此参考分支；必须由获准的集成人将最小增量应用于实际已交接候选SHA。
唯一工单：https://github.com/Ethancao258/bsv-all-platform/issues/52 ；原始需求 #59；统一架构A：https://github.com/Ethancao258/bsv-all-platform/blob/docs/living-architecture-register-v1/docs/architecture/five-year-foundation/BSV_ALL_2026_2031_ENTERPRISE_ARCHITECTURE_FOUNDATION.md 。不修改固定正文，不新建服务或主库。

## 0. 接管顺序与停止点
PM按 P0→P1→P2→P3 执行，P4可选。专业审核视角：生产计划/仓储、食品安全、数据库、接口与安全、前端打印、质量测试、DevOps。是同一AI的模拟专业视角，不是假称聘请专家。
本分支已提供 services/api/supply/central_production_rules.py 及 tests/supply/test_central_production_rules.py。先运行 python -m pytest -q tests/supply/test_central_production_rules.py，随后 bash tests/supply/check.sh。仅在已批准隔离树执行。CI与实际打印不是同一验收。
P0只需核对C交接SHA、实际供货代码、A–G真实接通情况、D schema/迁移/权限、catalog已批准规则、原标签模板及设备。不要重新全系统盘点。先比对参考文件与实际版本，不覆盖C集成成果。代码从本PR逐文件移植或经审核cherry-pick，禁止整树checkout覆盖生产。缺D可继续纯逻辑/合成UI，但标BLOCKED，不建第二账本，不放行真实物料。
 
## 1. UI交付（复用 apps/hq-console/supply/index.html、app.js、style.css；门店与督查沿用现有共享页面及权限）
|页面|最少操作|字段/显示|
|---|---|---|
|总部-生产计划|选配送周期/门店→生成建议→确认|物料固定ID/名称、可用库存、有效在途、计划需求、建议量、单位、批准状态、异常|
|总部-制作任务|选任务→录真实制作时间及产量→逐瓶装量→核对放行|制作人由登录解析、配方/SOP版本、原料批次、损耗/余量、标准装量可改、保质期和死期预览|
|总部-标签|选已放行包装→批量打印/重印|原模板50×40mm HPRT T260L；物料、实际数量/单位、制作/死期、储存、来源、追溯码、法定字段；实际物理打印须验收，失败不得记已打印|
|总部-配送|选已放行包装→按门店拣货→核对后发货|来源、目的地、箱号、预计到达、发货人及真实时间、装量、死期；禁止过期或重复分配|
|门店-收货|打开配送单→扫描或逐行核实→一次确认|计划件数/量、实际接受件、隔离件、未收件、差异、收货人、时间、储存位；少货保持在途，异常明确隔离|
|门店-两份清单|点击打印→A4浏览器预览|到货表取签收事实（包括计划与实收、异常、签字）；死期表取全店有效/隔离剩余库存，包括旧货，过期优先，实际日期+星期+时刻，分日显示，最新修订与生成时刻|
|员工-上下班|原工作台按真实班次触发|到货准备、当前/今日过期、用法、隔离处置、交接；确认实际事实，不伪造考勤或销毁|
|督查|异常列表→复核|冷链、过期、差异、召回与整改；不直接改库存|
页面默认中文，员工只见任务及实际动作。按钮在请求未确认时禁重复触发，超时先查询原request_id，不生成新ID。打印文件必须逃逸用户文字，权限与数据源在服务器校验。当前纯逻辑A4输出是可集成的初始HTML；到货表仍需计划/未收及异常原因投影、死期表需要日期分组及分页/QR验证、真实打印另验。不得宣称页面已上线。

## 2. 权威数据/接口映射
A catalog批准规则只读（既有 GET /api/items → A /items；catalog adapter复用既有版本读取）。B身份实时核权；C组织门店库位只读；D唯一生产/配送/库存写入，E独立督查，F视觉候选，G通知。供货服务 routes 与D路径沿用现有 main.py / gateway.py / shipment_contract.py。以下是待核实的新增命令契约候选，不是已部署端点；若实际已有同义端点优先适配而非再造：
|操作|建议挂载/既有路径|请求（服务端推导actor/scope）|事务/响应|
|---|---|---|---|
|计划预览|原 /api/reorder/preview|门店、周期、物料、可信用量、库存、在途|复用calc_reorder；仅建议|
|计划确认|候选 /api/production/plans|request_id、expected_version、已确认计划行|D写计划及版本；返回COMMITTED或明确未提交|
|批次/包装放行|候选 /api/production/batches|request_id、计划引用、生产时刻、产量、单位、原料批次、包装量、余量损耗、批准规则引用|D从A取批准快照，服务端核验真实规则、资格和安全；validate_split；生成/复用稳定ID；状态RELEASED需真实放行|
|标签投影|候选 /api/production/packages/{package_id}/label|读取包装ID；重印命令需request_id|D已放行事实生成，不改变死期；重印审计独立|
|配送创建/备货/发货|原 /api/shipments、prepare、dispatch|保留旧payload；兼容新增包装ID关联；禁止旧路径绕过效期|D锁定包装、核权、转在途、追加流水、审计/outbox|
|签收|原 /api/shipments/{sid}/receive|request_id/version、实收包装、逐件条件及差异；旧scanned_codes+condition兼容为同条件组|D锁单与包装；receipt_intent仅辅助校验，实际质量/召回/单位验证在D；合格/隔离/在途分流，返回真实提交与新版本|
|两份A4|候选 /api/shipments/{sid}/arrival-sheet；/api/inventory/expiry-sheet|授权门店/版本|D一致性只读快照；arrival_sheet/expiry_sheet纯渲染；不得用cache正式签收；PDF可走浏览器打印|
|处置|候选 /api/inventory/packages/{package_id}/dispose|request_id/version、实际处置量、原因|D验证隔离状态/剩余量、记账、审计；不自动假销毁|
|待办|复用 #46/#47 工作台及班次事件|真实shift_id、门店、task key|service_ops幂等upsert；shift_due仅提供死期任务候选，ETA/交接另接事件|
|照片/AI|原 /api/photo-preview；后续草稿接口|受限账号、候选数据、证据引用|不直接D写；人工核对普通操作不额外经理审批|
原demo /api/shipments使用按件数量及DEMO批次，正式端禁止把其结果当真实生产。现有 D /supply/shipments、/inventory/balances 等通过配置注入；不直连外部任意URL。接口能力须在真实D实现，gateway仅转发，不能在本服务增加新权威账本。 
## 3. 持久化逻辑（不执行本节为DDL）
实际schema先读；现有主键可复用即复用。catalog版本：批准效期、时间起点/规则类型、单位、储运、开封规则、SOP。production batch：batch_id、原料批次、实际制作时刻、maker、批准规则快照、产量/单位/损耗、放行。包装：package_id、batch_id、实际初始量、当前库存位置、有效死期、开封时刻、状态与版本；label_id引用包装不重新发物理ID。shipment_id及分配记录关联包装、源/目的、ETA、发货事实；现有shipment_package如是分配关系不可因换单重置包装ID。库存使用已有stock_lot_id/movement，入库/在途/隔离/报损各记流水，余额是投影。receipt_id是采购域键，不复制命名。所有量用NUMERIC(18,4)明确mL/g/piece；不混算。不在此分支造迁移，待实际schema核对后新增兼容字段/约束、回填、恢复测试。
D事务顺序：实时服务端身份授权→幂等键与请求摘要检查（相同请求重放返回原结果）→固定顺序锁shipment及package/库存行→校验门店/版本/状态/数量/批准规则/死期/召回→写事实、库存流水、审计及outbox同一事务→保存幂等结果→提交后返回。幂等表唯一键按既有actor scope+request_id；重放也须当前授权。竞争、死锁有限重试，禁止负库存。消费outbox按event_id及业务版本去重；消息失败不撤销真实签收。 
效期：纯代码仅支持明确批准的elapsed_seconds和opened_seconds，实际数据库若以天、自然日、制作后冷却等不同规则定义，必须由catalog确认起点/语义，不得把任意文字转换为秒。now>=effective_expiry即时禁用；开封、召回或更早安全限制收紧，重新打印不延长。召回早于制作等异常需走隔离/追溯而不是强行渲染。产品实际期限必须批准，代码不设默认期限。
## 4. 最小合成验收数据和预期
两瓶450+350mL，生产800mL，0余量0损耗；模拟发货2件；签收450mL，350仍在途，随后隔离350。D总量800不消失，库存可用450、隔离350；重复确认不增加余额。另一旧瓶剩余100mL今日到期，死期表必须列旧瓶；当天午夜跨日及等于死期禁用。打印重印不变身份/效期，A4计划2、实际合格1、隔离/在途逐件清楚。合成值不是实际配方或合法期限。
负例：NaN/Infinity/负量/重复包装、单位不明/超产、缺批准规则、无权限/撤权/跨店、错单/版本过期、过期收货只隔离、网络202不假成功、重复请求/不同内容、消息重放、实际销毁必须确认、旧接口与POS不回归。用真实DB隔离事务并发测试，纯函数测试不替代该验收。
## 5. 腾讯云执行清单（门禁解除后）
1. C完成#58并提供候选SHA和交接证据；供货执行人独立worktree，仅移植本候选增量，不使用公开参考分支直接覆盖当前服务器。
2. 验证原测试及新测试；核实A–G真实契约、D实际事务、既有label模板。确认变更文件owner；仅针对缺口编写adapter、真实D事务与兼容迁移。先P1/P2再P3，P4独立。
3. 在既有隔离发布机制中启用供货功能，保留原路由、原权限及fail-closed；真实浏览器操作：生成计划→制作→打印→发货→部分签收→两份A4→开闭班→隔离/处置。实测HPRT打印、扫码及A4版式，未做标NOT_RUN。
4. 对照真实数据库流水/余额/审计/事件、备份隔离恢复，确认无重复记录及跨店泄漏。输出PR、精确候选SHA、CI、实际网页/打印验收、回退、阻断和授权状态。生产部署另获批准；不直接切入口。先一合法生产点→一授权店，再根据真实验收扩大。
5. AI反方复核必须检查：原包码与跨配送历史是否兼容；D是否唯一写入；数量单位是否正确；实际效期与召回能否即时禁用；重复请求是否可重放；纸质与电子清单是否同步；旧货是否遗漏；真实权限是否绕过。发现缺陷在同一工单增量修复，不重写架构。
## 6. 参考依据
- 2025北京食品经营许可审查细则（2025-08-01生效）https://www.beijing.gov.cn/zhengce/zhengcefagui/202509/t20250912_4201051.html ：集中加工配送应核实实际许可/场地；不能凭系统上线推断经营合规。
- OWASP API Security Top 10 2023 https://owasp.org/projects/api-security-project ：对象级授权、认证与功能级授权风险。
- PostgreSQL 17 当前文档 https://www.postgresql.org/docs/17/explicit-locking.html ：行锁用于并发事务，不替代应用幂等。
- AWS当前事务outbox指导 https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html ：业务记录及事件同事务、消费去重。
这些是当前规范和实现指导，不是第三方对BSV的认证。实际部署、许可、保质期、设备、D后端及业务效果均待验。

## 7. 本轮实际代码接口与尚未实现项（接管时不要重写）
|函数|已提供的能力|调用前必须满足|
|---|---|---|
|ApprovedRule / expiry|批准时长、开封及早期限、精确时刻|由catalog适配器验证规则版本；禁止客户端自行批准|
|validate_split / quantity|Decimal、单位、逐瓶总量与损耗闭合|D事务中锁住批次，保证原料与包装关系|
|PackageFact / available|只读事实、剩余量与当前禁用判断|真实D快照，召回/开封更新有效截止时间|
|receipt_intent|部分签收、跨店/重复/过期拒绝、隔离意图|D事务内锁单与包装，核权、召回/质量、真实数量；不直接接HTTP|
|arrival_sheet / expiry_sheet|A4 HTML投影、已提交签收、旧库存与日期排序|授权且一致的D快照；demo默认开启；正式输出还需完整字段与设备验收|
|shipment_reconciliation|计划、合格、隔离、未确认逐单位对账|已发货不可变清单与实际签收快照；用于补齐到货表差异区|
|label_preview|50×40mm文字版式、实际装量、制作及死期|仅预览，必须加实际二维码、批准字段、源信息并验证HPRT；不是打印结果|
|shift_due|稳定死期任务候选|真实班次与service_ops upsert、另接ETA及闭店交接|
尚未实现：真实D存储事务、批准catalog适配、HTTP路由/前端接线、正式打印二维码/设备、A4整合分页/日期分组与版本失效、班次/通知接线、AI草稿和POS扣库。不得声称整个系统已可使用。接管执行人按第5节落地并独立核查这些缺口。当前候选不含真实数据/凭据/迁移/新服务。
