# SUP-59 中央生产、配送、标签、效期、库存与员工任务｜唯一开发接管手册
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
