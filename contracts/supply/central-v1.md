# SUP-59 | 现有 D 服务接入契约 v1

[执行工单 #52](https://github.com/Ethancao258/bsv-all-platform/issues/52)

浏览器走既有 supply 进程的 `/api/central`。正式模式由其使用现有 D 主地址转发至 `/supply/central/v1`，请求带既有公司访问令牌。D 在同一事务内检查当前身份、法人、岗位资格、门店、库位和对象权限。D 必须复用原生产、仓储、配送、库存、审计与 outbox 归属。清单和标签读取同一个一致性快照，禁止读取备用或过期缓存。

| 请求 | 参数 | D 返回 |
|---|---|---|
| POST `plan-preview` | 源门店、目的门店、物料、下一配送时刻、用量与安全库存计划 | `{"state":"PREVIEW","data":{...}}`，供应库存及在途以 D 为准 |
| POST `plan`, `batch`, `create`, `prepare`, `dispatch`, `receive`, `open`, `dispose`, `recall`, `label` | 精确字段见 `services/api/supply/central_routes.py` 的 Pydantic 模型 | HTTP 200/201，`{"state":"COMMITTED","request_id":"原UUID","data":{...}}`，配送动作返回实存版本 |
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
