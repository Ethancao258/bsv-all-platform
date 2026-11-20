# ADR-R3.2-07｜总部地图管理与统一调酒的兼容集成方案

**状态：DESIGN_DECIDED / NOT_IMPLEMENTED / CODEX_NOT_STARTED / PRODUCTION_NO_GO**。本文件**决断工程设计**而非替代实际开发/主机验收。继承 `AGENTS.md`、R3.2架构母版与UX V2.2修订规格。V4.1依据SHA：`c51b58d67dabae53afcdf9851a80cdc93d4200f6`。

## 1. 已核查：两个不同的根因，不能只修复URL

1. `platform/lighthouse/internal-stage/ingress.py`将 `/hq` 指给身份管理，而旧地图编辑器 `apps/hq-console/bsv1/hq.html/js/css`也用 `/hq`。两套程序都存在，**不能合并和删除**。
2. `services/api/bsv1/app.py`在V4设备统一模式中显式拒绝全部 `/api/hq/*` 读写；旧地图 `bsv_one.is_hq/require_hq`依赖SQLite的本地 `HQ_ADMIN` 和 `staff.role=MANAGER`。V4 POS设备绑定会把本地角色设置为STAFF。仅恢复路由或去掉403都不安全。
3. 旧地图编辑器启动时通过 `/api/state` 获取旧POS会话CSRF，不能要求HQ管理员先有当班+POS设备才能编辑地图。
4. `bsv_one.py`已有原唯一布局版本账本 `bsv_layout_revisions, bsv_layout_ownership, store_layout_data, seats, table_groups`，保留版本控制、草稿、发布和历史回滚。`created_by/published_by`仍引用旧SQLite staff FK，安全桥必须处理审计映射。
5. `apps/store-console/bsv1/index.html/app.js`原 `#guideOverlay`已经有原料/成品图片、可视计时、制作完成/送达分离及返回真实地图。新的统一网页调酒UI不得重新建立订单和production tasks。
6. `device_pos.bind_actor`会增加 `staff_store_access`，所以**不能用它将HQ管理员接入地图编辑器**，否则地图授权意外变为POS店级授权。

## 2. 固定路由（不再交给Codex做架构决策）

| URL | 原程序 | 处理 |
|---|---|---|
| `/hq` | identity总部人员审批 | **原样保留** |
| **`/hq/stores/layout`** | 旧BSV1总部地图编辑器 | **新增独立入口，映射现有hq.html** |
| `/hq/stores/layout/assets/app.js`与`style.css` | 原hq.js/hq.css | 新增安全的文件映射，复用原代码，不建SPA |
| `/api/hq/status,stores,modules,layout,art,image` | POS原HQ地图只读API | 同URL复用，增加集团身份授权 |
| `/api/hq/stores/create,layout/draft,layout/publish,layout/restore,image/upload` | POS原地图命令 | 同URL复用，增加准确动作授权 |
| `/pos` | 原每店独立座位图/POS | 不变 |
| `/menu` | 原V9内部报价预览 | 保留、只允许原授权范围 |
| `/cocktail/` | V13公开菜单 | 保留公开页面，不向匿名客人注入内部工作台导航 |
| `/craft/` | 原公开精酿入口（当前404） | 不占用 |
| `/work/craft` | **未来**员工新网页调酒视图 | C批受控新增；必须复用现有POS订单和出品任务 |
| `/supply-ui/` | 既有独立供货 | 不变 |

改 `ingress.py` 时：显式将 `/hq/stores/layout` 和其静态资产分流到POS现有服务；`/hq` 精确匹配identity，`/api/hq/*`继续走POS；新身份授权的内部service endpoint必须在Ingress浏览器层阻断。测试匿名、无权限、旧路径、同名请求和URL变体，**未知URL不得默默返回另一种管理界面**。

## 3. 由identity.A授权，POS SQLite仍是地图唯一写入者

### 3.1 精确动作权限

仅增加4种受控HQ动作到现有 `domains/workforce/identity/core.py` 的管理动作注册表（而不是创建第二张HQ员工表）：

- `hq.layout.read`：进入地图管理页、浏览可见范围内的店/图纸/历史；
- `hq.layout.edit`：拖动保存布局草稿、图片上传、从历史建立**新草稿**；
- `hq.layout.publish`：确认将指定版本发布到原POS点单地图；
- `hq.store.register`：将**organization已批准并存在的永久store_id**注册为POS地图壳，不允许直接凭POS UI给公司发正式新店号。

管理者必须具有当前有效EMP/BM任职、BM_MANAGEMENT资格和**独立审批生效的对应Grant**；拥有 `hq.people.read` 或POS当班资格**不自动获得地图管理权**。现有真实组织主数据与法律主体映射未核实时，**真实新店注册BLOCKED**，隔离合成数据可演练。

API→权限：
- 地图页、状态、门店列表、布局、图片与历史GET：`hq.layout.read`；
- 草稿、恢复草稿、图片POST：`hq.layout.edit`；
- 发布POST：`hq.layout.publish`；
- 新店登记POST：`hq.store.register`。

### 3.2 单一后台身份会话桥

新增到现有 `services/api/identity/api.py` 的**仅服务端可用**端点：
`POST /api/v1/identity/hq-layout-session`。
- 使用独立service ID `layout-admin`、独立token和明列动作/法人scope；POS从真实浏览器 `bsv_identity_session` Cookie安全读取后，**由POS服务端**传递Bearer会话给identity。
- 请求schema只允许 `{action,legal_entity_id,store_id?}`。**不接受请求者自填 tr_code/auth_subject_id/role/granted/is_hq**；服务端identity校验Bearer会话、当前person、EMP/BM资格、任职、资格、Grant，决策实时读取A，TTL=0。
- 写操作要求浏览器当前Origin匹配SSH本地域名+身份CSRF `X-CSRF-Token`/`bsv_csrf`与会话关联，并在identity后台验证。普通POS `X-BSV-CSRF`是另一会话体系，**不能混用**。内部服务证书/令牌绝不传浏览器/写Git。
- 返回最小 `{allowed,decision_source:"A",cache_ttl_seconds:0,action,legal_entity_id,store_id?,actor_tr_code?}`；POS检查请求动作、合法主体/门店及实际结果一致才继续，否则FAIL CLOSED。
- 新 `integrations/auth/identity_client.py.authorize_hq_layout` 使用现有安全HTTP适配技术，但**不能复用** `authorize_device`/`authorize_pos`（这两者是当班POS门禁）。身份源不可用503、无权403、无会话401；禁止回退旧SQLite HQ_ADMIN。

### 3.3 跨库actor与原审计

只允许POS服务端经已核验身份响应构建不可从HTTP body伪造的 `HQLayoutActor`（封装TR、动作、法人、店、request_id）。受控适配器调原 `bsv_one.current/draft/revisions/publish/rollback_to/upload_image/layout_art`，不得复制其布局业务算法。旧 `require_hq` 的V3专用路径与新V4集团权限必须分离；**不要用一个客户端可填 `trusted:true` 字段绕过鉴权**。

已有 `created_by/published_by` 和事件审计使用旧SQLite `staff.id` 外键，采用已核验TR→不可登录的本地审计投影/显式alias，保留旧actor ID，不重写历史；不能使用 `device_pos.bind_actor`，不添加 `staff_store_access`，不给HQ自动POS会话/有效PIN/设备权限。若映射前置条件不满足，拒绝写入并给出需核对旧码的反馈，禁止临时造另一套员工编号。隔离SQLite加法迁移须显式有恢复演练，正式CloudBase不写。

旧 `hq.js` 改为由 `GET /api/hq/status`（HQ权限）初始化，不再调用需要POS设备的 `GET /api/state`；POST用身份 `X-CSRF-Token`。读写都重新鉴权，不允许一次首页GET通过后永久缓存权限。

### 3.4 原地图的实际数据边界

`organization`拥有永久store_id/法律主体；POS原SQLite布局服务仍是**现阶段唯一地图写入者**。未经批准不得复制到identity PG或另一个“总部地图库”。BSVM、BSVS、BSVT JSON+SVG和座位/邻接保持不变（13、13、17节点）；BSVF无地图，不借用其他店。旧 `bsv_one.publish` 拒绝OPEN桌次、版本不一致、跨店ID、重新复用停用ID及非法合分桌，发布失败不可自动重试/强制覆盖。历史回滚只创建新草稿，必须再审批发布。地图版本历史与操作记录保留。

## 4. 地图编辑器现有界面要优化，而不是重画

在现有 `apps/hq-console/bsv1/hq.html/js/css` 原DOM上做小差异修改：
- 顶部“总部 / 门店 / 座位地图”与当前门店、发布版号、管理员和安全返回HQ；
- 左侧门店/真实图纸、版本历史、是否就绪；中央**原1100×580相对坐标画布**；右侧选中座位、名称、人数、类型、顺序、X/Y、左右邻座与合分桌；
- 原拖拽、添加座位、停用、上传图片、导入/导出JSON、保存草稿、发布、旧版生成草稿、新店建图**全部保留**；
- “保存草稿”和“确认发布”分开摆放。发布前展示店名、当前/待发布版本、是否有未结桌次、座位修改摘要；不可从浏览器猜危害数量。发布需要二次确认，审核权限独立；
- 网络超时提示`结果未确认，请查看当前地图版号和历史再决定是否重试`。不允许连续点击导致双发布。手机可查看，精确拖图以PC/平板为主；键盘/数值坐标应可编辑。
- 原地图没有真实图纸时展示明确的空白编辑候选，不伪造店面；保存草稿**不改变POS线上布局**。禁止使用红色警报遮住整个编辑器导致无法处理。

## 5. 新网页调酒界面只能复用现有POS制作内核

现有 `#guideOverlay` 和 `app.js openRecipeGuide/guideTaskList/guideStartTimer/guideFinishConfirm/guideDeliverConfirm` 以及 `/api/production/recipe` 和原POS订单/制作任务接口属于既有资产。R3.2的“重做统一网页调酒引导”**允许设计新的员工页面和步骤呈现**，但**不得创建第二套order/production_task/claim/finish/deliver数据库或事件**。

未来 `/work/craft` 只是按原order_id/line_id读取已有任务的员工私有视图；与原POS引导共享同一业务服务、配方版本、权限、状态机和幂等处理，继续显示原料/成品图、位置、倒计时、员工制作与送达分开确认。员工中途转岗/撤权/班次结束要由后端实时拒绝不符资格的制作提交；退出后回到原POS真实座位地图且选中桌位可核验恢复。旧引导保留，直到新页面通过独立三店出品回归才可评估是否作为默认入口；**不可删除原引导**。未接通的位置树显示“本店位置待维护”，不能由AI推断酒架位置。

## 6. 固定拒绝项与12项实机验收（当前NOT_RUN）

| 验收ID | 唯一判断 |
|---|---|
| G01 | `/hq`仍是人事，`/hq/stores/layout`才是总部地图，`/pos`原店图；匿名/普通员工不可读取地图敏感JSON |
| G02 | 有人员查询权无地图权403，有地图read只能GET不能POST，edit不可publish；申请/审批Grant复用集团现有双人制度 |
| G03 | 旧SQLite HQ_ADMIN不能在V4无A授权写地图；伪造角色、请求法人、其他店、无CSRF、错误Origin、身份A失联均拒绝且0写入 |
| G04 | 已授权BM不需要POS当班班次、门店设备或员工PIN即可管理授权范围地图；管理地图不增加店级POS access |
| G05 | 密云/顺义/通州独立地图JSON/SVG、原座位永久ID/邻接节点数13/13/17不变，富民街没有图不显示其他店图 |
| G06 | 旧拖动/图片上传/JSON导入导出/新增与停用座位/草稿/二次发布/历史新草稿/新店候选建图均通过 |
| G07 | 门店有OPEN桌次禁止发布，版本冲突409，审核请求重复时不生成重复版本；演员TR与旧SQLite审计对应 |
| G08 | POS原点单、转桌、合分桌、结账登记、保洁、历史、收据与登录权限通过回归 |
| G09 | POS内嵌视觉调酒原料图/成品图/缩放/视觉计时/任务领取/制作与送达两次确认/返回地图全部保留 |
| G10 | 未来 `/work/craft` 只能引用同一个订单行和制作状态，重复提交不多制作；无资格/错店/撤权拒绝 |
| G11 | 320/375/768/1024/1440px，原地图可触达，HQ桌面/平板可操作，数据未知态不假成功 |
| G12 | CI、实际部署SHA、隔离主机HTTP、浏览器截图、SQLite备份/还原、迁移版本与回退独立提交证据；未执行写NOT_RUN |

## 7. 最后边界

这份ADR已经锁定“路由/集团授权/旧业务/用户页面/唯一主数据/异常”的工程方案，**但尚未写代码或在主机验证**。第五个门店的规范ID、真实organization主源和正式CloudBase schema仍UNKNOWN；只阻断对应真实组织迁移和生产操作，带合成资料的隔离实施可以进行。真钱、客户PII、正式短信及生产部署继续NO_GO。

安全原则参照OWASP Authorization/CSRF/IDOR和Microsoft Strangler Fig，始终按deny-by-default和incremental adapter实施。
