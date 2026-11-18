# BSV ALL｜中央供货模块接入契约 V2.0

## A. 不可修改的边界

- 公司中央数据库是唯一权威账本。正式模式的程序只通过 A–G 别名指向**公司统一 API**，不可私自建立第二套产品、人事、门店、财务主表。
- `app/demo.py` 的 SQLite 仅用来本机演示业务事务。在 `BSV_MODE=remote` 它不会实例化，`app/cache.py` SQLite 只储存**已读取快照和待同步命令**，不是正式账本。
- 公司正式库存每次增减必须由统一 D 服务在 PostgreSQL **单事务**提交并生成审计流水。客户端和 AI 无数据库 SQL 权限。
- 读到备用只读源或本地缓存的结果，必须带 `meta.stale=true`。只用作观察或待复核建议。
- 允许公司调整数据源URL、数据库物理位置、内部表名。**D/A/B/C适配器的HTTP契约稳定**，由公司统一 API 负责后端迁移与版本兼容。若公司 API 协议本身修改，则仍需修改契约适配器；不能承诺任何字段变化均无需代码修改。

## B. A-G 业务适配器契约（业务端口前缀由 `config/sources.example.json` 注入）

### A｜产品和物料主数据

`GET A.primary/items?stockable=true` -> 数组 `[{"item_id":"P000015","sku":null,"name_zh":"京都雪","unit":"mL","package_size":"450","approved":false,"track_package":true}]`

`item_id` 绑定V9固定ID，不可将 `sku`、`item_id`、`name_zh`混成同列。V9未核准时 `approved=false`；M资产目录等不可配送物资 `stockable=false`。批次、生产许可、包装规则应在公司主数据补齐，不能用程序虚构。

### B｜人事组织及授权

`GET B.primary/auth/me`，请求携 `Authorization: Bearer <company_user_token>` ->
`{"employee_id":"...","department_id":"...","stores":["BSVS"],"roles":["receive","inspect"]}`。

B须独立核验令牌是否有效、部门成员有效期与授权门店。程序仅缓存已验证身份5分钟；生产 D/E 必须再次验证动作级权限，不可完全信任浏览器传来的 `store_id/actor_id`。只持久化业务事件中的员工固定ID及操作时的部门快照。

### C｜门店和库位

`GET C.primary/stores` -> `[ {"store_id":"BSVS","name_zh":"顺义鸡尾酒吧","kind":"store"} ]`。

公司需批准中央仓的稳定 ID；当前 `DEMO-WH` 仅为虚拟演示仓，不能进入生产库。V9 T000001/T000002/T000003/T000004 分别是一组历史网点记录ID，与 BSVM/BSVS/BSVT/BSVF 对应，应使用映射契约，不得并行建立重复主键。

### D｜唯一供应链事务 API

| HTTP | 路径 | 业务效果 |
|---|---|---|
| GET | `/supply/shipments[?store_id=]` | 权限范围内的配送任务 |
| GET | `/supply/shipments/{shipment_id}` | 包装明细、状态、乐观锁版本 |
| POST | `/supply/shipments` | 创建草稿（request_id） |
| POST | `/supply/shipments/{id}/prepare` | 冻结明细，校验包装及有效许可 |
| POST | `/supply/shipments/{id}/dispatch` | 原库位到运输在途，同事务写库存流水 |
| POST | `/supply/shipments/{id}/receive` | 运输在途到门店可用/隔离，同事务写库存流水 |
| GET | `/inventory/balances[?store_id=]` | 权限限制的账面库存与在途数据 |
| POST | `/inventory/counts` | 五档盘点观察；不能直接冲账 |
| GET | `/inventory/counts` | 历史盘点观察 |

三类写入的通用规则：`request_id` UUID + `expected_version` 整数；创建草稿不需要 expected_version。返回最新 `state/version` 或 `409 VERSION_CONFLICT`。所有写入事务具唯一约束 `(client_scope, request_id)`；同一包装ID不得被两个收货动作重复入账。相同 request_id 的重放必须返回第一次的相同结果。

**注意**：正式 D 必须有强事务、源库存非负约束、包装状态校验和 outbox。当前独立模块提供调用方和演示实现；真实中央API及表模式由汇总AI与现有服务共同实现。

### E｜独立督查

`POST E.primary/inspections` 接收：`{request_id,store_id,subject_department,subject_employee,results:{expiry,temperature,hygiene,equipment,pricing,previous_actions}}`

每项 `OK|ISSUE|NOT_CHECKED`。需要落地 `inspector_employee_id`、检查时部门快照、被核查部门与人员引用、证据对象键、状态与后续整改任务。原始异常只能形成调查任务，不可据此直接做员工经济处罚。

### F｜AI候选，绝无正式入库权限

`POST F.primary/extract`（multipart `file`）-> `{"recognized_package_ids":[],"item_candidates":[],"unknown_regions":[]}`。

模型不得编造无法读取的序列号；若照片无法验证唯一包装身份就返回 UNKNOWN。前端收到候选后还要人点击确认及 D 的强事务复核。

### G｜公司统一通知

G 由企业级 outbox 消费者统一处理。D/E 同事务写事件，G 按 `department_id + store_id` 解析当前有效员工名单。严禁多个模块分别维护一份员工群组通讯录；通知是否发送、送达、已读、完成应分离记录。独立程序尚未配置实际G发送动作。

## C. 实体与主键建议

- `item_id` 固定产品主键；`sku`（独立、可空）用于可变业务分类；`name_zh` 展示。
- `store_id` 公司批准的规范门店码；`warehouse_location_id` 公司另行批准的仓储库位ID；`T00000x` 为原V9记录别名映射。
- `employee_id`/`department_id` 只由公司HR发放；历史操作记录不可被员工离职覆盖。
- `lot_id` 生产批次；`package_id` 唯一包装；`shipment_id` 调拨单；`request_id` 幂等请求；`movement_id` 库存转移事件。
- 计量必须有明确 `base_uom` 与包装到基础单位转换因子。M 生产成 P 后消费在总部记录，卖出C时扣门店 P，禁止重复扣 M。

## D. 不可省略的验收场景

1. 发10收9：总部 -10，在途 +1，顺义 +9。
2. 重扫、网络重试、客户端重复提交：只提交一次。
3. 两设备并发收同一瓶：一成功一 409，无负库存。
4. B 人事身份变更/离职后不能再执行新操作；旧事件保留历史 actor_id。
5. D 中央不可用：本地待同步，前端不得显示“收货成功”；恢复后在同一 request_id 下由 D 唯一过账。
6. 无效 SKU/未批准产品/已失效批次：不得自动入库到 AVAILABLE。
7. AI 只能生成候选；不能自动产生看不到的包装编号。
8. 五档盘点只能产生观测数据，不能自动冲账。
9. 正式事务 commit 成功但通知失败：不影响库存，通知异步重试且不重复通知。
10. 定期快照和 pg_dump 必须分别校验，并在**独立数据库**验收恢复。

## E. 集成顺序（不得跳步）

1. 只读盘点真实服务器、已运行服务、现有数据库 schema、GitHub 仓库，确认 A–G 是否已有对应 API。
2. 将主数据库已有表映射到本契约；优先复用现有模块，新增表必须经迁移审核，不得在生产环境自动执行 `contracts/central_schema_proposal.sql`。
3. 配置仅服务端可读的密钥、内网访问、HTTPS、跨站策略、身份；测试A/B/C只读与D/E事务的真实权限。
4. 在预发布数据库用演示包装码测试10发9收、并发、回滚、缺网重放与跨店拒绝。
5. 生产启用前，必须证明远程真实交易已完成备份恢复演练，不能只看到演示网页便当作上线。

## F. 对汇总AI的明确执行指令

> 接收本包后先读 README、INTEGRATION_CONTRACT、真实服务器的现有代码与 PostgreSQL schema。不可猜现有表名。将 app/gateway.py 的 A–G URL 映射到现有统一 API；在测试环境实现 D 的事务及 E 的异常写入，复用公司产品、人事、门店的主键。永不部署 DEMO ledger 为正式系统，不改其他模块原有接口，不直接将五档估算入正式库存。测试全部通过后出具真实部署清单、端点、数据库迁移差异和恢复验证报告，才允许上线。保留回滚，不执行未经授权的删除或覆盖。
