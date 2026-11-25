# POS-08｜通知、任务、日报与异常管理 Architecture V1.0
DESIGN_READY；不是已部署代码。遵循 V2.0 固定路线，独立开发，待 POS-05 经营事实与 POS-07 权限具备后启用。已核查历史部署参考 SHA 2052ef51f011be3c5898d816932d8982f420b752；现网增量优先。EXISTING=该 SHA 实际源码；NEW=候选设计，实施前核对现网。
## 1 数据源与权威
| 领域 | EXISTING 入口 | 权威与边界 |
|---|---|---|
| 数据路由 | config/data-contracts.json；services/api/shared/data_contracts.py::resolve_database | BSV_DB_URL 是中央 PG 配置；legacy 仅兼容，不是第二主库；新增模块登记 registry/resolver |
| 人员与授权 | config/modules/identity-data-sources.json；contracts/identity/identity.openapi.json；services/api/identity/academy_policy.py:139-167；integrations/auth/identity_client.py | A 唯一身份授权；BSV_DB_URL/兼容 BSV_DB_A_URL；B只读参考，LOCAL灾备不授权；/api/v1/identity/me、authorize、/api/v1/academy/pos-authorize |
| POS事务 | services/api/bsv1/app.py:99-125 connect/db_read/tx；176-300 DDL；457 record；497 bsv_day_filter；507 report_escalations；532 state；620 receipt | BSV_DB_PATH 对应 SQLite，现有订单来源；新模块不得直接改写订单。通过现有 POS 内部只读接口/事件出口 |
| 人员映射 | services/api/bsv1/bsv_device_pos.py::bind_actor, scope_from | bsv_pos_tr_projection: TR→staff.id；未映射历史人员标记 UNKNOWN |
| 制作任务 | services/api/bsv1/bsv_collab.py::schema/tasks_for_store | production_tasks、production_finishes、production_deliveries；在线不等于出勤 |
| 所有权 | config/data-ownership.json | task_id/service_event_id/incident_id → service_ops；document/version/acknowledgement → knowledge；tr_code/employee_id/shift_id → workforce；audit_event_id→event_audit |
| 契约 | contracts/API_AND_EVENTS.md；contracts/database/EVENTS.md | 源事件不可覆盖，保留 source_system/source_event_id/actor/法人/门店/版本/UTC |
配置从当前服务环境解析，不硬编码连接串、真实人员、密钥；禁止输出环境全量。PG 候选 schema 为 service_ops、knowledge；检查已有迁移和 owner 后扩展，不复制主档。正式迁移之前 POS 原始事实仍在 SQLite；权限每次向 A 核验，不从快照授权。
## 2 模块与文件候选 NEW
services/api/service_ops/（若已有 owner 实现则复用）；knowledge owner 的文档发布与确认模块；contracts/service_ops/pos08.openapi.json；config/data-contracts.json/路由/权限注册；apps/store-console/bsv1/app.js 原工作台、/staff、/hq 增量入口；使用现行正式迁移目录及测试。不要重建登录或独立地图。
## 3 逻辑模型 NEW
名称为候选，已有表则扩展；UUID 或 owner 发码，含 legal_entity_id、store_id/明确 HQ 范围、UTC、version、actor。跨库稳定引用由 owner 验证，不伪造 FK。
- notice/notice_version：id/version/title/body/scope/publish_at/expiry_at/requires_ack/status；发布版本不可覆盖。
- notice_recipient：notice/version/recipient_tr unique；受众快照；新入职覆盖规则单独配置。
- notice_ack：notice/version/recipient_tr unique，read_at、ack_at、request_id；阅读与确认独立。
- task：task_id/source_type/source_ref/assignee_tr/owner_tr/priority/due_at/state/version/creator；系统任务 unique(source_system,source_event_id,rule_version,assignee_scope)，人工任务 unique(scope,request_id)。
- task_event：event_id/task_id/from/to/actor/expected_version/reason/evidence_ref/occurred_at/payload_hash，不可覆盖。
- task_evidence：id/task_id/storage_ref/hash/type/scan_state/creator；权限、限额、保留期；不混入身份或合同签名原件。
- daily_report/revision：store/business_date/version/cutoff/source_watermarks/metrics_json/completeness/generated_at/submitted_by/reviewed_by/revision_reason；unique(store,date,version)。
- incident：source_event_ref/category/severity/state/owner/reviewer/resolution；仅待核查，不写 payroll。
- event_inbox/outbox：source_system/source_event_id/event_id/payload_hash/scope/state/attempt/next_attempt；同载荷重复返回原结果，异载荷隔离。
状态：NOTICE DRAFT→PUBLISHED→WITHDRAWN；READ 与 ACK 独立。TASK OPEN→IN_PROGRESS→SUBMITTED→ACCEPTED 或 RETURNED→IN_PROGRESS；授权取消；overdue 是未终结且超过 due_at 的派生标记。转交/期限更改/复核必须 reason + expected_version。禁止自动把打开网页、心跳、超时、查阅时长认定失职或扣薪。
## 4 日报来源与计算
从 POS db_read 一致性快照或源事件构建，先核对实际表字段。短期以 audit_events 的单调 id 加 source instance/epoch 作 watermark，事件 ID 不跨库碰撞；恢复备份须对账。长期同源事务 outbox，消费幂等；只传最小字段，不传 PIN、token、手机号、采购成本。
| 指标 | SQLite 来源（BASE） | 定义 |
|---|---|---|
| 开桌/人次 | visits(id,store_id,created_at,guests,status)；visit_seat_events | distinct visit_id，转桌不重复；人数为登记值 |
| 订单/件数 | orders.visit_id→visits；order_lines(order_id,quantity,status,created_at,price_cents,list_price_cents,discount_cents,checkout_id) | 有效行数量，撤销/未结/演练分列；成交快照整数分，折扣依 receipt 口径 |
| 登记结账 | demo_checkouts(id,visit_id,store_id,amount_cents,status,created_at)；order_lines.checkout_id；visit_closures | TEST_SETTLED 不是到账；分次以 checkout_id 去重 |
| 制作/送达 | production_tasks(line_id,visit_id,assigned_staff_id,claimed_by,state,assigned_at,claimed_at) + production_finishes(maker_staff_id,finished_at) + production_deliveries(deliverer_staff_id,delivered_at) | 分开统计；等待=送达-真实下单时间；未送达截至 cutoff；缺失 UNKNOWN |
| 清洁 | seat_cleaning(dirty_at,cleaned_at,cleaned_by) 当前态；bathroom_checks(id,bathroom_id,store_id,staff_id,checklist_json,checked_at)；audit_events | 历史以检查和事件为准；bathrooms.interval_seconds 默认7200，读取实际配置 |
| 异常 | alert_escalations(category,entity_id,cycle_key,occurred_at)；audit_events | 每源事件一次；需核查 |
| 真实收款 | POS-10 verified payment/refund | 未接入 NOT_CONNECTED；不是虚构零 |
业务日复用 bsv_day_filter，Asia/Shanghai，营业日切点由配置批准；[start,end) UTC，跨午夜不重计，晚到数据生成新 revision。记录 cutoff、来源水位、覆盖率、缺失/核验状态；测试不进真实报表。
## 5 API 与授权候选 NEW
显式网关路由 /api/v1/ops/ 与 /api/v1/knowledge/，不落入泛 identity 路由。基于统一身份 A 逐次检查主体、法人、门店、岗位、动作；现有 authorize_device/authorize_pos 作基础，新增 action 必须同时注册身份端，不能只放行 POS。浏览器 actor 不可信；写操作 CSRF、request_id、版本校验；服务间认证。
| API | action 候选 |
|---|---|
| GET /api/v1/knowledge/notices | knowledge.notice.read（本人受众） |
| POST /api/v1/knowledge/notices/{id}/read 或 /ack | knowledge.notice.ack（版本、本人） |
| POST notices /{id}/publish /withdraw | knowledge.notice.manage/publish（授权管理范围） |
| GET /api/v1/ops/tasks?scope=mine | service_ops.task.read |
| POST /api/v1/ops/tasks | service_ops.task.create |
| POST /api/v1/ops/tasks/{id}/transition | service_ops.task.execute/review/assign（按状态） |
| POST /api/v1/ops/tasks/{id}/evidence | service_ops.task.execute |
| GET /api/v1/ops/reports/daily?store_id=&business_date= | service_ops.report.read |
| POST /api/v1/ops/reports/daily/{date}/submit 或 /review | service_ops.report.submit/review |
| GET /api/v1/ops/incidents；POST /{id}/resolve | service_ops.incident.read/review |
错误 401/403/409/422/503；未知动作默认拒绝；返回 items/next_cursor/scope/source_status。事务+行锁/CAS；网络不在 SQLite 写锁内；店长不是全法人 HQ。
## 6 页面及步骤
08.01-02 员工通知角标、版本确认；08.03-05 本人任务、店长分派、反馈/复核；08.06-07 日报及 HQ 授权范围异常汇总；08.08 语音输入仅预留 consented adapter，不默认录音。复用 POS 侧窗、/staff、/hq，保持地图、转桌、配方；制作任务直接跳原业务，不复制一份待办。日报可按日查看并追溯原记录。调度使用现有受控 scheduler，若无则候选 systemd timer，幂等生成。
## 7 验收
异店/撤权拒绝；旧通知版本保留；双设备重复提交只一次且旧 version 409；隔离开桌→下单→出品→送达→分次登记→清洁→日报，金额与原报表核对；跨午夜/恢复/晚到事件生成更正；来源不可用显示 UNKNOWN；测试流水不计真实收款。先在独立 worktree 开发、迁移和关键回归，现有发布机制切换，保留回滚；不直接改不可变发布目录。汇报实际复用文件/schema/API/测试/部署/网页路径/缺陷。