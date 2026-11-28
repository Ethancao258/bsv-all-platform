# SUP-59 | 现有 D 服务接入契约 v1

[执行工单 #52](https://github.com/Ethancao258/bsv-all-platform/issues/52)

浏览器走既有 supply 进程的 `/api/central`。正式模式由其使用现有 D 主地址转发至 `/supply/central/v1`，请求带既有公司访问令牌。D 在同一事务内检查当前身份、法人、岗位资格、门店、库位和对象权限。D 必须复用原生产、仓储、配送、库存、审计与 outbox 归属。清单和标签读取同一个一致性快照，禁止读取备用或过期缓存。

| 请求 | 参数 | D 返回 |
|---|---|---|
| POST `plan-preview` | 源门店、目的门店、物料、下一配送时刻、用量与安全库存计划 | `{"state":"PREVIEW","data":{...}}`，供应库存及在途以 D 为准 |
| POST `plan`, `batch`, `create`, `prepare`, `dispatch`, `receive`, `open`, `consume`, `dispose`, `recall`, `label` | 精确字段见 `services/api/supply/central_routes.py` 的 Pydantic 模型 | HTTP 200/201，`{"state":"COMMITTED","request_id":"原UUID","data":{...}}`，配送动作返回实存版本 |
| GET `inventory`, `labels` | `store_id`，标签另传重复的 `package_ids` 参数 | `{store_id,revision,packages:[PackageFact...]}` |
| GET `shipment` | `shipment_id`，可另传 `store_id` | `{id,src,dest,version,state,eta,sent_at,sender_id,planned,receipts}` |
| GET `plans`, `tasks`, `exceptions` | `store_id`，任务另传 `phase=START\|END` | 对应存量计划、班次任务视图和异常。督查整改证据仍来自 E |

GET 返回表内 JSON 对象本身。PackageFact 字段以 `central_production_rules.PackageFact` 为准，数量以十进制字符串表示，时间为含偏移的 ISO 8601 字符串。收货事实含 `package,accepted,held,receiver_id,source_store_id,sender_id,sent_at,received_at,committed`，异常另含 `exception_reason`。计划清单固定于发货时，签收后的开封、处置不能改写历史到货单。任务是供现有班次/工作台读取的投影，`phase` 不能作为已打卡证据。催办、报损、异常处置和整改确认必须保留事实记录。

## 事务接线与迁移候选

以下是从现有 `central_schema_proposal.sql` 映射到 D 的最小**增量迁移清单**。先核对真实表、历史迁移账本、唯一键及旧数据含义后确定列名和 DDL。不得因此重建现有表，或给旧数据补写未经核实的批次、装量和效期。

| 已有逻辑对象 | 最小兼容增量及约束 |
|---|---|
| D 生产计划、批次 | 关联目的门店、原料批次引用和 A 的批准规则、配方及 SOP 版本；所有生产量/单位守恒。A 规则按版本解析后保存事实快照。无确认版本禁止放行 |
| 永久包装与配送分配 | 包装实体保存初始量、剩余量、版本、生成和当前死期、库位及状态。配送单的包装关系保留历史，不复制永久 ID。用 D 既有包装键或唯一映射，限制同一包装只有一个有效分配 |
| D 库存流水 | 锁定配送单和被处理包装，按固定顺序锁库存。合格可用、异常隔离、未收在途各自记账。使用规范单位，不能把旧按件库存解释成毫升 |
| D 幂等、审计、outbox | 已有作用域加请求号唯一键；复核当前权限后查重放，校验请求摘要。同一事务保存业务事实、流水、审计、outbox 和回执 |
| 标签及打印历史 | 引用永久包装 ID，记录准备、重印及人工确认的独立事件。驱动或打印窗口开启不能当作已印。重印不得改变批次、装量、制作时刻或延长死期 |

启用前核对既有旧版配送 API 对新包装的行为。旧版路径必须转到同一事务或明确拒绝受控包装，防止绕开批次校验。D 未明确确认提交时，调用方不排队、不写本地账本、不报成功；同一请求号用于安全重放。A、B、C、E 以及真实班次的现行授权和字段按主机核对结果配置。合成事务仅使用既有 demo SQLite 文件。

参考 [PostgreSQL 17 行锁文档](https://www.postgresql.org/docs/17/explicit-locking.html) 和 [北京市食品经营许可审查细则](https://www.beijing.gov.cn/zhengce/zhengcefagui/202509/t20250912_4201051.html)。系统只读取已经批准的效期及储运规则，经营许可、实际效期和食品追溯不能由测试或代码推定。

`central_authority.approved_catalog_policy` 使用 A 主源的批准规则候选视图 `GET /production-policy?item_id=&recipe_version=`。示例规则字段见函数返回校验。A 已有等价视图时只映射接口；未获批准、起算语义无法核实、缺储存或 SOP 时拒绝放行。该 helper 未接通真实 A。

`central_authority.commit_d_command` 提供 psycopg 3 单事务壳及 PostgreSQL 幂等提交 (约定默认 READ COMMITTED)。它调用 D 所有者现有的 `authorize(cursor)` 与 `mutate(cursor)`，不会建立连接、建表、安装驱动或自动启用。真实字段映射与读写命令应依据已核验 schema。唯一键以现有正式配置为准，和提议 SQL 不同则仅适配 SQL 名称和作用域，不另建幂等账本。

### 正常耗用增量
`POST /supply/central/v1/consume` 接受 request_id、store_id、package_id、expected_version、amount（正十进制字符串，单位取正式包装）。D 在同一事务内实时核验收货操作权限、对象归属、已开封、合格、未过期、未召回、版本、剩余量及幂等。扣减实际耗用并记录 CONSUMED 流水，不作为报损，不改变原签收事实或效期；余量为零仍保留 ACCEPTED 历史状态，投影为不可用。禁止借此写假 POS 订单。浏览器、演示实现及测试候选已增量提供；实际 D 权威实现必须遵循现有正式 schema，不得用 demo 账本替代。

### 统一工作台 HTTPS 会话（候选）
正式供货页面通过原 `/supply-ui/` 命名空间进入，配置 `BSV_MODE=remote` 与 `BSV_SUPPLY_WEB_ORIGIN=https://<已批准正式管理域名>`。沿用 `bsv_identity_session` HttpOnly cookie、`bsv_csrf` 及 `X-CSRF-Token`；写入须精确匹配配置 Origin 与 Host。内部入口需原样转发 Host/Origin/cookie/CSRF，不依赖伪造 scheme。身份 B 实时授权仍为前提；当前 B production connector 尚有独立门禁，不因此放宽。API bearer 调用者兼容保留；浏览器不再弹令牌输入。未接通、无授权时隐藏操作区、提供重试及返回统一工作台。原 internal-stage 保持只读，demo 不挂正式域名。本候选不改共享网关或工作台配置，待 C 获准集成后接入。

### D 实现候选（非正式迁移）
`central_d_postgres.DWorker` 是真实 PostgreSQL 事务候选，使用原 `supply.shipment`、`shipment_package`、`movement`、`idempotent_result`，不是演示 SQLite，也不新建另一套权威库存。计划、批次、签收、标签为增量事实。仅 `bsv_sup59_isolated_candidate` 可执行 `sup59_postgres_isolated_candidate.sql`；实际 D 的 schema/已有账本和 outbox 尚未查明，正式迁移必须经 D owner 映射并审核。DWorker 要求六个明确的真实接线回调：connect、identity（实时动作/法人授权）、location（C 稳定库位）、policy（A 批准规则）、consume_ingredients（按批准配方与真实原料批次、数量同事务扣库）、record_event（现有审计及 outbox 同事务）；无默认演示回调，无自动建表。D worker 不能安装在第二个库存服务上。若 D 尚不存在，由公司确认唯一 inventory owner 后将候选落实到该域。旧 API 写受控包装必须被 D 拒绝或接入同一实现；所有虚拟流水桶及余额投影映射到 D 已批准的库位约定。当前余料须独立分装或记录真实损耗才允许放行；未经确认的历史数据不得迁入。员工待办仍是投影，实际考勤及 E/G 需接线。隔离 PG 测试用专用数据库，真实原料扣减和审计回调采用明确合成 fixture，仅验证事务边界。不得据此宣布主机正式通过。

中央配送单列表直接通过 `GET /supply/central/v1/shipments?store_id=` 查询 D，返回 `{items:[{id,src,dest,state,version,created_at}]}`，前端不再依赖旧配送列表。候选 PG 迁移包括受控包装及配送单旧路径误写保护和追加式库存流水保护；事务标记只防止误用，不替代数据库角色及 API 权限。正式迁移须按 D 实际表适配，不擅自部署候选触发器。

### 可启动 D 权威服务候选与原料实际扣库
`central_d_runtime.create_authority_app` 为显式启用的 ASGI factory，不自动迁移、不建立新数据源。若现有 D 服务已存在，应把 `d_router` 安装在原 D 应用内，复用其真正 stock_lot / audit / outbox 表；仅在确定没有对应事实所有者实现并经批准后，才按候选方案映射。当前参考 SQL 的 `supply.stock_lot` 及 `event_audit` 扩展仅用于可执行隔离测试，不授权正式新建表。
A 批准视图须额外提供 `yield_amount`（按产出单位）、`recipe_inputs:[{material_id,unit,amount}]`（按该产出量的基础单位投入量，每个物料合并为一行）。C 主源返回已确认的 `legal_entity_id` 与 `approved:true`；不接受演示仓。程序以实际分装前总产量按批准配方比例计算投入，在被选择的实际原料批次中按FEFO扣减，拒绝未知/过期/隔离/跨仓/单位不符/数量不足/无效多余批次；与产出、D 流水、幂等、审计及 outbox 同事务提交。非精确四位小数投入须批准规则处理，不自行舍入。G 消费现有 outbox；未送达不修改库存事实。启动环境需要既有已批准的私有 D DSN 和 service token、远程 A/B/C、准确 schema，并显式 `BSV_SUP59_D_AUTHORITY_ENABLED=1` 与 `BSV_SUP59_D_SCHEMA_REVIEWED=1`；不能用开关替代正式授权或实际迁移审核。

### A/C 既有主数据所有者接线及工作台
`central_source_adapter.CatalogPolicyAdapter` 直接使用已有 catalog repository 的固定 P/M ID 与当前 source SHA；经所有者批准、SHA 固定的结构化规则投影是原目录发布物，不是第二套主数据。不得根据自由文本保质期推定规则；原 P 生产标准未批准、配方输入无真实物料、目录版本改变或投影校验失败，均拒绝。A 在原服务挂载 catalog_router；C 在原组织服务挂载 organization_router。C 的获准组织投影由同一权威来源发布，包含真实法人、仓/店、TR 到部门映射、as_of/valid_until、批准引用、SHA（有效期最长72小时，按实际源刷新）；B 正式授权使用此同一当前投影且继续实时核对员工及 grant，未配置仍拒绝生产。统一浏览器写请求的 CSRF 除入口 Host/Origin/双提交校验，还转 B 校验实际会话。原工作台在供货台账真实可读取且已登录时展示授权门店待办，不伪造班次、完成或通知。C/身份/目录的正式 owner 与真实发布资料仍须确认，不得用测试投影上线。
