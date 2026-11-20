# Codex唯一执行指令｜BSV ALL V4.2 R3.2｜G0与既有功能兼容接入

**本文件用于用户下一轮主动启动Codex时复制或引用。现在没有启动Codex、没有运行代码、没有授权云端发布。** 输入以该文件、`docs/architecture/ADR_R3_2_07_HQ_LAYOUT_AND_CRAFT_BRIDGE.md`、R3.2主架构/UX修订、Issue #14为准；不可凭旧单页演示重写原POS。

> **节省Codex执行量的优先规则（2026-11-21）**：本文件给出全部业务验收要求，但**不要求Codex每次改代码都执行全部测试或逐条分析全部日志**。实现时遵循下面“精简开发测试→GitHub PR CI→最终人工隔离验收”三层模型。Codex只跑和改动直接有关的1–3个快速测试；长耗时集成、浏览器及全量回归让GitHub Actions在PR提交后自动运行。只有当相应CI失败，才读取失败作业的最短相关日志并修复。最终放行仍必须由GitHub同一提交SHA的8个指定CI作业全绿＋被批准的隔离实机验收证明，绝不降低地图、授权、资金、订单的安全红线。可直接使用超短入口文件 `docs/ops/CODEX_R3_2_G0_HQ_LAYOUT_LOW_COST_START.md`，无需复制本文件全文到Codex聊天。

## 0. 角色、主旨、固定边界

你是唯一执行工程师Codex，任务是**在V4.1原程序上修复总部地图管理权限/路由冲突，保护既有内嵌调酒引导，并为完整R3.2 A—G后续工程清理G0门禁**。已选架构不可变更，不要提出新应用体系、重复数据库、微服务或新产品概念。允许在无法取得真实云资料时生成离线合成E2E并标明BLOCKED；不允许编造结果。

**只允许**GitHub代码分支、合成的隔离数据库、CI/测试；**禁止**合并主分支、操作生产CloudBase、操作真钱/短信、使用真实个人信息、部署公网、自动覆盖Lighthouse旧8765/8767、触发云端费用或直接修改真实门店地图。

开始前先读取（严格此序）：
1. `AGENTS.md`；
2. `docs/architecture/BSV_ALL_V4_2_R3_2_FINAL_ARCHITECTURE.md`；
3. `docs/architecture/ADR_R3_2_07_HQ_LAYOUT_AND_CRAFT_BRIDGE.md`；
4. `docs/design/BSV_ALL_R3_2_UX_V2_2_SPEC.md`；
5. `contracts/v4-2/R3_2_USE_CASE_INTEGRATION_MAP.json`和`UX_V2_2_EXISTING_APP_PRESERVATION.json`；
6. `docs/ops/CODEX_WORKFLOW.md`、`config/change-routing.json`、`config/data-ownership.json`、`docs/ops/CURRENT_STATE.md`。

准确指定工作源：`design/v4-2-r3-2-ux-v2-2`设计分支的最终HEAD；从这个已提交SHA创建**独立实施分支** `feature/v4-2-g0-hq-layout-bridge`，严禁在PR #15/#16设计分支直接写生产程序。核对Git HEAD与GitHub PR来源；如缺文件、branch SHA变化、设计合约冲突，STOP并提交清晰阻断记录，不能自行改方案。

## 1. G0：先保存源代码保护证据（不得跳过）

在合成环境读取并计算：
- 对照V4.1 `c51b58d67dabae53afcdf9851a80cdc93d4200f6`的340个原跟踪文件，生成路径→git blob SHA表及差异报告；当前设计分支只加设计文件且不得改原地图。
- ``services/api/bsv1/store_layouts/stores.json`、BSVM/BSVS/BSVT JSON/SVG快照校验哈希、seat_id/邻接、三店13/13/17个节点、富民街BSVF layout_file=null；保留这些文件内容原样。
- 梳理所有原地图API及HTTP methods、旧HQ页面的CSS/JS、旧POS `#guideOverlay`、`openRecipeGuide/guideFinishConfirm/guideDeliverConfirm`、旧V9内部菜单和V13客户菜单；写出机器可读route-map并确认无冲突。
- 检查identity.A已注册BM权限模型及服务token限制；地图事实继续仅在POS SQLite，法人/门店主码读取org权威源或明确UNKNOWN。
- 32业务用例状态记录证据类型`CODE_PRESENT/CI_PASS/HOST_VERIFIED/MOCK_ONLY/BLOCKED/NOT_IMPLEMENTED`及SHA/来源日期；不得把代码存在等同正式上线。
- **任何真正要修改的核心文件路径列入allowlist；本任务不允许删除任何既有程序、地图、菜单与测试。**

G0产物：`docs/ops/RETAINED_FUNCTIONS_V4_2_G0_REPORT.md`、`contracts/v4-2/G0_EXISTING_ROUTE_FACTS.json`（仅机器事实，不是第二数据owner注册表）；更新`CURRENT_STATE.md`只用实际可验证证据，不能虚报现场结果。

## 2. Phase HQ-1：恢复旧地图独立路由，不能降低安全

**允许路径**：
- `platform/lighthouse/internal-stage/ingress.py`
- `services/api/bsv1/app.py`
- `apps/hq-console/bsv1/hq.html`、`hq.js`、`hq.css`
- `apps/staff-center/identity/workbench.html/js`、`apps/hq-console/identity/hq.html/js` **只允许添加受控导航**
- 相关 `tests/internal-stage/*`、`tests/ui/*`
- `config/change-routing.json`仅最小加入路由模块关联，不动任何既有ID。

**精确路由结果**：`/hq`仍是identity人员审批；`/hq/stores/layout`是旧HQ可视化地图编辑器；其JS/CSS从`/hq/stores/layout/assets/{app.js,style.css}`获取原文件；原`/pos`地图、`/academy`、`/supply-ui/`、`/cocktail/`、`/menu`均可访问且业务不变。客户端不允许自行提供“是否HQ管理员”标志。

**必须先写失败测试**：
1. 没有HQ身份GET地图页/GET敏感API拒绝；POS普通当班不具备HQ地图权；人事HQ可读但无地图Grant仍拒绝。
2. 当前内网`/hq`内容仍是身份HQ；新URL内容为原地图编辑器并含`#canvas,#seatLayer,#save,#publish`。
3. 旧URL`/hq.html`等不能在V4无权限时返回特权编辑器。
4. 路由未知路径不会误返回地图或身份页；内部身份授权端点无法从Ingress匿名直接调用。
5. 公共`/cocktail/`匿名只能看顾客V13内容，不能因为`?from=pos`伪造内部工作台返回/权限；已有内部使用场景改用有权限的安全返回入口。

上述失败测试先提交，再写最小的网关/旧页面映射代码。禁止建立新的现代化单页地图编辑器。

## 3. Phase HQ-2：集团身份授权桥，不能使用本地HQ_ADMIN替代

**允许路径**（在HQ-1基础）：
`domains/workforce/identity/core.py`、`services/api/identity/api.py`、`integrations/auth/identity_client.py`、`services/api/bsv1/bsv_one.py`、`services/api/bsv1/app.py`、`platform/lighthouse/identity/migrations/*`（仅经现有受控schema preflight证明必要）、`tests/identity/*`、`tests/bsv1/*`、`tests/internal-stage/*`，必要时新增`services/api/bsv1/bsv_hq_layout_bridge.py`。

**四种权限必须分开**：
`hq.layout.read`、`hq.layout.edit`、`hq.layout.publish`、`hq.store.register`。均属HQ管理动作；按照现有资格模型要求EMP、BM任职及BM_MANAGEMENT、有效独立Grant；不借用`hq.people.read`、普通POS令牌或SQLite本地role。Grant申请与审批仍为原双人分离。

新增identity服务端 `POST /api/v1/identity/hq-layout-session`：仅接受来自`layout-admin`独立服务身份认证和Bearer浏览器会话，body仅`action/legal_entity_id/store_id?`，实时查询identity.A，返回最小允许信息与actor TR，不接受客户端提供auth_subject_id/role/tr_code；拒绝任何受限scope或身份服务不可用。

POS通过 `integrations/auth/identity_client.py` 专用 `authorize_hq_layout()` 逐请求校验，不使用 `authorize_device()`/`authorize_pos()`。写入前经身份CSRF与Origin验证；对每个HTTP endpoint按ADR精准映射动作。POS从已核实organization关系确认门店法律主体；无法核对真实法人时BLOCK真实新店登记，合成测试允许预先批准的虚拟新店ID。Ingress必须禁止浏览器调用内部服务决策端点。

**最重要的旧数据库兼容规则**：旧 `bsv_one` 所有地图版本/校验/事件规则继续被调用；新增受控 `HQLayoutActor` 服务端对象进行集团授权，不允许原来的`bsv_hq_roles`成为V4绕过通道。旧SQLite内历史`staff.id`只作为FK审计来源；若必须创建TR投影，**不得调用`device_pos.bind_actor`（它会插入staff_store_access），不得给地图管理员增加POS权限/设备/班次/有效PIN**。缺少可信TR映射时返回阻断，不得假造临时人物码。

旧HQ页面必须改为 `GET /api/hq/status` 获取本人及权限/CSRF所需提示，不再从`/api/state`要求POS当班；POST使用和身份会话绑定的`X-CSRF-Token`，切勿在JS混用`X-BSV-CSRF`。对每次变更后台写出真实SQLite审计TR及旧本地actor引用，超时/重复提交先查询修订版本，不可以直接重放危险publish。

**最后强制恢复原地图权限与事务测试**：
- V4已授权BM仅有read只能浏览，edit不能publish，publish需要具体Grant；撤权后立即403，源A断线503且地图不变。
- HQ编辑器显示3家原图，拖动并保存DRAFT后POS仍看原地图；PUBLISH后同店POS读取新版本且其他店无变化。
- 部署/服务重启后已发布自定义图、邻接、图片和历史版本仍保存；不能重新从seed覆盖HQ发布内容。
- 两管理员版本竞争409，OPEN桌次发布拒绝，历史恢复仅生成草稿，新店在未组织批准情况下不得拿到合法store_id。
- 审计actor与实际TR一致，但地图Grant不会令员工进入未授权门店POS。
- 原V3测试模拟旧授权仍在其原有隔离上下文按既定前提运行；V4不能有旧授权退化入口。

**旧总部导航中的V9内预览小修复**：旧地图编辑器包含`/menu`链接，它仍由POS原门店会话控制。不能让只获`hq.layout.read`的管理员误以为已获POS资格；无该资格时将链接标为“需门店点单授权”并提供安全返回，保留旧POS合法会话下的实际`/menu`页面。此任务不创建新的跨店价格权限，也不把用户路由到V13公开菜单来替代内部预览。

## 4. Phase Craft-Preservation：保护原调酒引导，准备后续C批复用

**本任务先做保护性测试和调用契约，不直接生成第二套新调酒页面**（新UI按R3.2-C批专门小卡执行）。
- 原`#guideOverlay`及材料/成品照片、放大、视觉计时、制作完成和送达两次确认、任务导航、返回座位地图必须有浏览器回归。
- POS原`/api/production/recipe`、原制作任务和订单行仍是唯一写入来源；在`contracts/v4-2/CRAFT_EXISTING_REUSE_CONTRACT.json`中记录前后端真实接口、任务状态、适用配方版本、门店资格和错误状态。只登记事实，未经确认的产品库位标UNKNOWN。
- 未来`/work/craft`以同样order_id/line_id访问原领域服务，只是新视觉视图；旧POS引导保留作为向后兼容入口，不允许出现两个库存扣减或两套制作计时事实。
- 暂不修改原调酒后端状态机、会员、真实收款、库存权威主库。若因测试发现原内核功能缺陷，写真实FAIL并作为后续C批单独修复，不擅自做全量重构。

## 5. 测试优化：开发只跑定向测试，集中提交CI与隔离验收

**这是最终验收覆盖清单，不是Codex开发期间每次提交都要手工跑一遍的命令清单**（本提示生成前均NOT_RUN）。按如下顺序执行：

1. **每次代码编辑时（Codex工作中）**：只跑新改文件的语法、地图静态哈希和1–3个最相关的快速正/反例；命令若已成功且源代码未改变则不重跑，日志只留成功/失败摘要。高风险权限改动至少包含“有权允许、无权拒绝”；地图写入至少包含“草稿不发布、真实发布、开桌拒绝”。不要创建3套内容重复的浏览器测试。
2. **每次阶段性PR提交后（GitHub Actions，非Codex聊天）**：由仓库现有`.github/workflows/validate.yml`自动运行全部CI作业；**不要让Codex同时在会话中手工再跑同一整套**。当前workflow设置`push`和`pull_request`均触发，可能针对同一SHA产生重复CI，未来可在单独批准的工作流小改动中改为“feature PR仅跑pull_request，集成分支跑push”；本任务不擅改发布CI策略。
3. **CI失败时**：仅报告失败job、测试名称、相关十数行错误和SHA；Codex仅修改对应文件并重跑该失败测试。若同一错误连续两轮无法定位，停止并交给ChatGPT做差异与日志独立审查，不允许无限自动重试。
4. **准备合并／申请隔离部署时**：必须保留现有`bsvctl.validate_ci`约束，验证同一HEAD SHA、事件`pull_request`、完整workflow成功，包含8个必需作业`architecture,bsv1,menu-v13-1,supply-v2,identity-r2,db-contract-preflight,lighthouse-internal-stage,v4-1-integration`。不得因“减少测试”关闭/跳过这八项。实际SSH/业务验收仍需人工批准，由原控制面在隔离主机执行，不能以CI代替主机真实服务验证。
5. **节省成本的方向**：删除重复新增测试，优先给既有`test_one_foundation.py`和现有identity/CI脚本补1–2个定向断言；浏览器只保留一条HQ拖图→草稿→发布→POS读取的新主流程和一条未授权拒绝主流程，其余用更快的HTTP/单元测试覆盖；老调酒导引未改代码则使用现有自动回归或一次最小浏览器冒烟，不重造全套长测试。必要时才能新增命名明确的测试文件。

**最终必须覆盖的业务与反例**：
- `tests/bsv1/test_one_foundation.py`全部通过且保护3张地图数据与HQ草稿/发布/历史回滚/新店逻辑；
- `tests/bsv1/test_device_pos.py`身份会话中断、当班与设备权限；
- `tests/identity/test_hardening.py`双人审、TR恒定、跨法人拒绝；
- `tests/menu-v13-1/*` V13语言、搜索、日夜、选酒清单与内部V9菜单不失效；
- `tests/supply/*` 供货与督查旧接口和隔离阻断不改变；
- 在`tests/internal-stage/`既有集成脚本中**优先追加最少必要用例**覆盖真实隔离A/SQLite、四权限、跨法人、CSRF、失联；仅在现有文件无法清楚扩展时新建`test_hq_layout_bridge.py`。
- **只加一个核心Chromium冒烟场景**：HQ地图拖拽→草稿→有权发布→POS同店新版本；原三店图通过哈希/HTTP低成本检测；现有浏览器基础设施优先复用，必要时才独立文件。
- **原POS调酒后端未改时**优先保留原测试和一条最小页面冒烟，不新增重复全业务浏览器套件；只在未来C批改变引导行为时补专门E2E。
- 对本次实际修改的HQ页面，以1024和1440为两档浏览器核心尺寸；320/375/768使用静态或现有响应式验收，最终合并前补一轮覆盖。原POS/菜单未修改时不用每次重新截图5个尺寸。
- 任何已有POS seat.id、邻接、发布历史及三家SVG/JSON改变，必须STOP且回退。

## 6. Codex可碰与不可碰的真实范围

**本次允许改**：上述经过点名的identity/HQ map/POS桥/Ingress/有限导航和原测试、现有registered域目录下的隔离加法迁移与本次`docs/ops`证据。任何新逻辑必须复用同一POS SQLite地图service、现有identity A管理权限和原订单出品任务，不新增进程。

**本次禁止改**：
`services/api/bsv1/store_layouts/*.json`、`store_layouts/art/*.svg`、既有seat_id和neighbor_graph；原POS全部其他功能逻辑（转桌/下单/结账/保洁/出品）的行为性重写；V13客用菜单版式/原菜品；正式CloudBase、真钱/现金充值、短信、永久自然人主码、数据库正式迁移、任何生产环境发布。不得直接合并PR #15/#16；不得修改原Windows离线V2.8包。

## 7. 精确提交与STOP门槛

分三次独立可审核提交：`G0 route/owner evidence` → `HQ bridge tests+implementation` → `map/craft UI preservation tests & docs`。如果需要额外API、服务、DB表、用户问卷或全新单页架构，**不得自行扩展**，先写`BLOCKED / reason / affected_paths / safe_next_step`，只推进已确定的其他隔离工作。

PR必须报告：`base_sha,new_sha,changed_files,unchanged_store_map_hashes,api_routes,identity_actions,actor_alias_migration,positive_tests,negative_tests,CI_job_url,HOST_NOT_RUN_or_HOST_VERIFIED,sqlite_backup_restore,rollback,open_blockers`。CI绿仅说明CI通过；只有经过用户明确批准相应SHA的隔离Lighthouse真实部署与主机E2E才能标`STAGING_VERIFIED`。**真钱/正式顾客数据/正式CloudBase写入始终独立NO_GO**。

完成上述项目后，回到Issue #14的现成A—G执行卡，只按模块依赖开展R3.2的其余功能。**本单不授权一个任务一口气重写整个BSV ALL。**
