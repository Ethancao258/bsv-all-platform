# API与事件统一契约

## 对外入口

- 顾客公共接口：仅已发布的菜单、活动、合规营业信息，不能返回内部配方成本、薪资、员工隐私、采购合同。
- 员工接口：服务端逐次校验身份、门店范围、职位资格、授权行为与任务状态；前端隐藏按钮不代表安全。
- 支付结果：仅可通过经签名验证的持牌支付服务方回调/主动查单认定到账；本地勾选不能生成付款事实。

## 推荐公共元字段（应与真实10表核对）

`event_id, event_type, source_system, source_event_id, idempotency_key, legal_entity_id, store_id, actor_subject_id, entity_id, entity_version, occurred_at_utc, received_at_utc, schema_version, correlation_id`

**事件不允许悄然覆盖**；更正采用更正事件，业务状态机由服务器控制；离线补传要去重、排序与冲突核查。业务接口优先 `/api/v1/`；不将 API 路径写成实际服务器已部署事实。

## 订单联动

POS/线上下单 → `commerce.order_id` → 支付服务验签后 `payments.payment_event_id` → `service_ops` 制作/送达 → `inventory` 根据批准配方记录核对后的用料 → `operating_finance` 日结对账。

## 员工考级联动

认证 `auth_subject_id` → 员工 `employee_id` → `learning.credential_id`（课程/在线考核/实操/有效期） → `identity_access.grant_id`（岗位+门店+审批） → 门店工作台可执行的最小权限。敏感权限不由考试自动获得。
