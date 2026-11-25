# POS-07｜正式员工、学院、排班、场所与操作授权 Architecture V1.0
DESIGN_READY / 未实施。对应 Issue #41 B04/B05，V2.0 POS-07。BASE=2052ef51f011be3c5898d816932d8982f420b752 已读取源码；服务器最新有效改动优先。已有完整身份/学院程序，重点接通及正式化，不重新开发登录、发码和培训。
## 1 确切源码和数据访问
| EXISTING 资产 | 用途 |
|---|---|
| services/api/identity/api.py:1-51,186-207,302-338,421-567,640-717 | FastAPI；统一 /staff、/hq，会话及 CSRF，注册/核验/批准、任职、EMP/BM、grant、撤权、服务间授权 |
| services/api/identity/config.py:33-94 | 环境、认证提供者、数据源 A/B、可信来源及服务权限；生产强门禁 |
| services/api/identity/database.py::SourceRouter.session | SQLAlchemy A读写；事务提交/回滚；B仅受控非敏感只读，LOCAL不授权 |
| domains/workforce/identity/core.py | encode_index 65、stage_code 71、has_action 150、register 199、verify_registration 246、approve_registration 267、end_engagement 332、issue_stage 399、request_grant 451、approve_grant 483、revoke_grant 506 |
| domains/workforce/identity/models.py | 既有主数据 ORM，见下 |
| services/api/identity/academy_api.py | 课程、考试、实操、资格、排班、设备；650起 pos_authorize；93-131 当前 isolated() 门禁 |
| services/api/identity/academy_policy.py:86-167 | active_employee、training_reason、scoped_pos_action、schedule_reason、shift_for_now |
| domains/learning/academy_models.py | Course/CourseVersion/Enrollment/Attempt/Practical/Credential/Shift/Device；实际表名按ORM及迁移，不另建人员表 |
| integrations/auth/identity_client.py:50-75 | authorize_device→/api/v1/academy/pos-authorize，BSV_POS_IDENTITY_URL及受控服务token；只接受A的有效决定及匹配scope |
| services/api/bsv1/bsv_device_pos.py:90-141；app.py:1646-1697 | bind_actor、scope_from、remember、same_binding、same_authority；POS /api/pos/device-login，统一会话+设备+门店及CSRF |
| apps/staff-center/identity；apps/hq-console/identity | 现成个人中心及总部管理页面（不是 apps/store-console/hq） |
| contracts/identity/identity.openapi.json；config/modules/identity-data-sources.json；config/data-ownership.json | API、A/B/LOCAL路由、唯一owner |
数据访问：identity A 使用 SourceRouter；中央 BSV_DB_URL 指向 bsv_all_prod（BASE 禁止 isolated identity 使用中央URL），兼容 BSV_DB_A_URL，现网隔离 identity 可能仍独立PG库；核实实际系统服务配置和数据库名，不打印DSN、密钥或个人信息。POS SQLite BSV_DB_PATH 仅存 bsv_pos_tr_projection、bsv_pos_device_sessions、旧 staff 外键及操作记录，绝不作为独立身份权威。正式迁移在 POS-10 按域单写者切换；POS-07可先用批准的权威A环境完成授权研发。
## 2 EXISTING 身份模型及流程
domains/workforce/identity/models.py：Person=bsv_identity_people；CodeAllocator=bsv_identity_code_allocator；StageIssuance=bsv_identity_stage_issuances；AuthLink=bsv_identity_auth_links；AuthSession=bsv_identity_auth_sessions；Registration=bsv_identity_registration_requests；Engagement=bsv_identity_engagements；Qualification=bsv_identity_qualification_links；StageRequest=bsv_identity_stage_requests；ManagementAppointment=bsv_identity_bm_appointments；Grant=bsv_identity_grants；LegacyAlias=bsv_identity_legacy_aliases；AuthRecoveryRequest=bsv_identity_auth_recovery_requests；PrivacyRequest=bsv_identity_privacy_requests；AuditEvent=bsv_identity_audit_events；IsolatedUser 只供隔离。
永久自然人 TR 唯一；TRA0001→EMPA0001/BMA0001 同后缀，角色与人分离；复用 encode_index/stage_code，不另写发码器。approve_registration 已锁申请和 allocator (FOR UPDATE)、检查不同审核人与申请人、同subject重复、重复证据信号、事务发码+StageIssuance+AuthLink+审计；缺allocator不自动补号。旧人员通过 legacy preview/commit/rollback 经授权映射，重复自然人须人工核验，原始主码不变。
已存在 /api/v1/identity/registrations、/{request_id}/verify、/approve；/me；/admin/people、/admin/queue；/engagements、/{id}/approve、/end；/qualifications；/{tr_code}/emp/requests、/emp/issue、/bm/requests、/bm/issue、/bm/revoke；/grants、/{id}/approve、/revoke；/{tr_code}/suspend、/restore、/history；auth-recovery、redaction、legacy-import。完整路径前缀按OpenAPI。沿用既有字段和双审，不另建临时身份证件表。实际员工个人资料经批准合法主体、隐私告知、最少收集、受控凭证及权限后才入库；隔离账号和 DEMO_LEGAL 不用于真人。
## 3 正式化的两个真实阻塞
(1) config.py:40起 production 只接受 cloudbase_jwks、拒绝测试认证，要求 PG A、JWKS URL/issuer/audience、Secure Cookie、可信 origin、独立高熵秘密及真实注册法人。不要把环境改 production 就称完成，也不要删门禁。若现有合法 CloudBase/JWKS 身份提供者可用，优先复用（不代表 CloudBase 数据库为权威）；若无，独立设计并审查正式 OIDC/JWKS provider 适配器，验证签名/issuer/audience/exp/nonce、密钥轮换、账号恢复、撤权与HTTPS；未批准留隔离，继续开发。
(2) academy_api.py::isolated() 明确仅 isolated auth；academy_policy 及 academy_api 使用固定 LEGAL/ROLE，TerminalCheck.action 仅 pos.order.read/create。因此正式身份/学院/桌位细粒度授权不是简单改两个配置。NEW 受控 policy context：从认证主体、明确法人/门店、授权服务及已核实的真实门店注册表派生 legal_entity_id、store_id、role；逐一替换固定 LEGAL 依赖，按 scope 过滤课程、实操、资格、排班、设备及审计。保留隔离路由条件；正式路由独立验收开关、真实实体及经验证认证提供者；默认拒绝，不把 DEMO_LEGAL 自动映射为公司。 
## 4 操作授权复用与增量
原 has_action（150-190）要求 active person+EMP+有效任职+有效grant、scope匹配、资格；manager/hq 还需BM和BM_MANAGEMENT。academy_policy.training_reason 要共同课程及当前门店课程已发布、资料可读、考试通过、门店实操 verified、credential eligible且未过期；schedule_reason再检查grant；shift_for_now 确认同法人/店/角色及[start,end)；academy_api.pos_authorize 验证服务token范围、device.store/state/token_digest、training、grant、confirmed shift。现有 Academy /work、/admin、/courses及版本publish/retire/enroll/complete/exam/practical、/credentials/{id}/suspend或revoke、/eligible、/shifts及approve/confirm/cancel、/devices及revoke、/pos-authorize。复用所有步骤。
NEW 操作字典建议（先查已注册名称）：pos.order.read/create、pos.order.cancel_item/cancel_visit、pos.seat.transfer/swap/group/guest_count、pos.production.claim/finish/serve/reassign、pos.housekeeping.confirm、pos.checkout.register、pos.history.read、pos.audit.read、pos.report.export。POS-06/08/09/10各自细粒度动作同一注册机制。必须同步更新 ALLOWED_ACTIONS/ACTION_QUALIFICATIONS、Grant审批规则、TerminalCheck schema、受控服务 actions、identity_client及POS服务端动作映射；不能只扩展 ACCEPTANCE_ORDER_PATHS 或前端隐藏按钮。已有 read/create 保持兼容。培训资格对全部现场动作按批准政策生效，原 covered 仅针对 read/create，新增动作不可无意跳过资格。每次敏感操作由A重验，禁止长期缓存及 fallback。 
POS 设备会话：device_login 已分别核验 read/create、scope一致，bind_actor 仅为旧 staff 外键投影；本地 staff.role/store_access 不是权威。扩展 scope 加 legal_entity_id、授权类别及必要版本（兼容迁移），复用 same_binding/same_authority/fingerprint；逐请求匹配设备/员工/班次/门店/操作，旧身份会话撤销后返回403；跨店换班清旧设备会话，防止前一员工遗留授权。
## 5 POS-07.06/07/08 新增场所与临时访问
现场员工必须有正式任职、门店训练、已确认班次、绑定当前店设备、具体权限。位置仅为辅助验证，不能代替身份/设备/培训；浏览器位置可伪造、SSH/代理IP不等于真实位置。候选 store_presence_policy（store owner批准配置、版本、适用角色、有效期）、presence_check（主体/设备/店/时间/验证结果/精度/证据最小化），仅必要时采集经告知的定位；不持续跟踪、不存无必要轨迹。权限不确定或位置异常提示人工核实；无授权不能自动放行。
管理者远程通道：有效BM、管理资格、具体 scope grant、强认证及受控远程访问；不冒充现场打卡/制作/清洁；仅开放批准的远程管理操作。远程合伙人网页演练与正式员工工作分开。
临时访问：复用 Grant 的 valid_from/to 与审批、临时 Engagement 或既有受控授权记录；明确自然人TR、法人/门店、动作、截止、理由、双审/撤销。资格不满足不得临时授予真实制作或收款；只允许明确不需该资格的受控动作。到期服务端拒绝；不创建共享万能账号，不绕过正式认证。
## 6 执行及验收
07.01-02复用注册/发码/角色→03训练及实操→04排班→05设备→06位置辅助→07远程管理→08临时授权→09离职撤权。身份正式启用门槛与开发分离：可用合成数据完成全链路；经营者批准真实法人、认证、人员、政策后才录入真人。离职调用 end_engagement/revoke_grant 等现有事务，撤会话/现场权限，保留TR、任职历史、订单/制作/客户归因；POS-09客户承接消费有效的任职结束事件。
验收：同subject重复申请/并发发码无冲突；核验人不能批准自己；员工有密云训练但无顺义训练时拒绝顺义；有训练无确认班次拒绝；设备错店/撤销/令牌错误拒绝；班次到期与中途撤权立即拒绝；跨店及管理动作独立授权；A不可用禁止从B/SQLite放行；临时授权到期；远程管理不能生成现场履职；原订单/人员ID保留。隔离E2E+真实页面（真实数据需明确批准）；使用独立worktree、官方迁移及既有增量发布，不覆盖原SHA目录。报告实际scope、身份提供者状态、权限矩阵、拒绝测试、部署SHA、剩余真实审批。