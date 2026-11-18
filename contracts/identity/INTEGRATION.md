# 人员身份 R2 与集团数据域

TR 是 workforce 的永久自然人码。EMP/BM 共用后缀，以阶段颁发与实际任职、任命表达。既有 employee_id 归 workforce，供货试点只投影已颁发的 EMP 码。旧收银操作员仍按其历史 ID 记录，由审核过的法人、来源、旧码到 TR 的别名建立关联。映射预检只读，隔离批次提交返回新增 alias ID，回退按 ID 原子撤销并保留审计。

| 候选表组 | 集团核对 |
|---|---|
| people、allocator、stage_issuances、registration_requests、stage_requests、legacy_aliases、engagements | workforce 永久主码、人员申请与任职；待与实际集团数据核对 |
| auth_links、auth_sessions、grants、bm_appointments、auth_recovery_requests | identity_access；引用既有认证、法人和门店，不存生产认证密码 |
| qualification_links | 引用 learning 的 credential_id |
| privacy_requests、audit_events | 隐私请求与 event_audit 历史；正式落库前决定如何复用现有集团审计 |

PG17 隔离环境有 15 张业务候选表，另有一张隔离账号表及 Alembic 账本。候选 SQL 在本契约目录。CloudBase 只采用集团官方迁移流程，G0/G1 前不发布正式迁移。

POS 试点由 BSV_POS_IDENTITY_REQUIRED 显式开启，只支持已映射的状态读取、开桌、草稿和提交。现有 PIN和会话继续用于历史工作台，由集团会话、旧 ID 别名、法人、门店与岗位资格共同决定权限。试点未映射的写操作及旧 HQ 入口拒绝。供货 B 兼容接口以同一集团会话实时核验，返回逐岗位的门店范围。真实组织部门连接器未验收，生产 B 接口锁定；D/E 中央事务仍负责复核对象、跨店及独立审查职责。

现有身份总部页面执行 BM、法人和动作限制。正式部门级权威、真实自然人去重、学习资格签发与 CloudBase Auth 登录待核。Issue #5 排班、打卡、工时和 BYOD 保持独立需求，POS 登录不会生成打卡。
