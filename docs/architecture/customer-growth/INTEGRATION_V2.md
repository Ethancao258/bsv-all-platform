# BSV ALL｜正式界面与客户风味对接 V2｜工程交接

## 已完成（本独立分支）

顾客注册页 `apps/guest-web/member/`：独立网页、风味标签、可独立撤销的当班调酒师查看授权、会员卡及权益展示、微信公众号网页授权入口、可配置酒单返回路由。**所有客户可见文案已排除开发测试提示。**

员工工作台 `apps/staff-center/growth/`：在现有员工系统下提供「当前接待／客户认领／我的推广／我的签名」四个页签，移动端底部导航；门店必须由实际岗位授权列出，不能默认第一家门店。待认领列表仅临时识别码；原先签名版本可供本人查看。点单台集成入口 `pos-entry.js`，由受信POS生成短时有效的客户场次上下文。

后端 `services/api/customer_growth/app.py`：沿用候选存储用于隔离验证；`POST /public/taste` 管理用户主动提交的风味标签（最多2个）及**独立的服务分享授权**；`GET /staff/store-options` 从授权的人员系统获取门店；`GET /staff/guest-context` 要求已认证员工、POS签名上下文、现有POs门店与本次订单关联且生产强制调用服务端核验器；`GET /staff/signature-preview` 只允许本人查看加密签名母版；**不能凭客户编号查询所有偏好**。

## 现有集团域对齐

事实所有权以 `config/data-ownership.json` 为准：`customer_id`、`consent_id`、`loyalty_account_id` 在 `customer`；`touchpoint_id`、`attribution_id` 在 `marketing`；`tr_code`、`employee_id`、`employment_id` 在 `workforce`；`auth_subject_id`、`grant_id` 在 `identity_access`；`store_id/legal_entity_id` 在 `organization`；`order_id`、POS `visit_id` 在 `commerce`；`payment_event_id/refund_id` 在 `payments`；`settlement_id/payroll_run_id` 在 `operating_finance`；`audit_event_id` 在 `event_audit`。新 `customer_taste` 由 `customer` 负责，主键使用原 `customer_id`，不构建影子客户主表。

当前隔离ORM中的 `*_candidate` 和 `bsv_growth_*` 并非已经验证的CloudBase生产schema。**严禁执行 `Base.metadata.create_all()` 到生产。** 实际G0先读CloudBase、身份A、POS SQLite与线上表的字段类型/唯一索引/现有迁移版本及原生权限；G1确认加密备份及恢复后，对照 `config/modules/customer-growth-v2.json` 与 `contracts/customer-growth/pos-visit-context.schema.json` 生成候选正式迁移，再通过集团官方 `cloudbase/migrations` 审核执行。不要先建第二张用户或店铺主表。

## POS轻量对接：只加一个入口，不改写原收银订单

原POS点单界面在确认当班员工、门店、桌位/到店 `visit_id` 及自愿出示会员的 `customer_id` 之后，由**POS服务端**生成以下对象，使用 `BSV_GROWTH_POS_CONTEXT_KEY` 做HMAC-SHA256签名：

`{"customer_id":"<authoritative>","store_id":"<authoritative>","visit_id":"<authoritative>","iat":<unix>,"exp":<unix plus <=120s>}`

由服务端返回短期token，门店前端调用 `BSVGrowthPOS.openCustomerPanel({storeId,context})`。浏览器不生成签名、不传通讯录、不在前端永久储存客户ID。POS后台还需提供私网核验 `BSV_GROWTH_POS_VERIFY_URL`，对 `actor_tr, store_id, visit_id, customer_id` 返回均为true的 `allowed/active_shift/customer_linked/store_ownership_verified`。只要任一项目不通过就403，不展示偏好；连接失败则拒绝读取、保留常规点单能力。该核验器尚未在现有POS实装，**当前只是安全接入契约，不得声称完整POS生产联调已通过。**

风味标签只取客人本人填写的四类：`清爽轻盈`、`果香酸爽`、`甜香醇厚`、`烈酒本味`。系统不保存顾客被员工推断的心理、醉酒、过敏史或私人微信对话。客人关闭服务分享后，下一次服务端读取即时返回空标签，不能从POS缓存继续展示。没有顾客确认，调酒师正常问口味即可。

## 注册与支付原则

- 会员注册：扫码来源与真实到店证据分开；有可靠线上邀请时优先保留，现场员工只对未被开发客户申请认领。注册来源仅是门店来源，不直接产生提成。
- 微信公众号网页 `snsapi_base` 只拿当前公众号openid，无法假装自动获得姓名、手机号、头像。必须运营方配置公众号APPID、AppSecret、HTTPS回调与网页授权域名；微信公众号授权不等于微信小程序登录。未来可加短信OTP、支付宝授权适配器，不得虚构已连接。
- 当前POS `payment_verified=False`；不能将本模块候选账本写入正式员工工资或现金结算。支付事件只能由持牌支付渠道验签、对账并经受信内部服务签名后写入。
- 纸质返场卡只提供进入个人权益的入口；不得凭纸卡本身赠送或重复核销。
- 会员隐私说明在网页中具备可读说明；**真实上线前公司必须批准完整的隐私告知和联系方式**，通过 `BSV_GROWTH_PRIVACY_APPROVED=1` 发布闸门。不将“测试”文字露在客户和员工页面，但后端内部状态仍应准确标记隔离、待核验与不可支付。

## 不与并行Codex分支冲突

当前PR #20为 `feature/customer-growth-mvp-v1`；#17—#22涉及身份、POS总部地图等其他工作。建议此V2单独建**基于PR #20头提交的叠加Draft PR**，不直接覆盖其他工作、也不合并到main。对接时只校验并映射已有 `identity.A /api/v1/identity/me`、`POS订单/会员关联` 与 `CloudBase`，不要求Codex重新制作这两个网页。Codex的唯一环境依赖工作是G0/G1、POS受信上下文签发及核验、真实数据迁移、微信运营方凭据、支付对账与生产发布。任何未知=拒绝而非默认允许。

## 验证

- `python -m pytest -q tests/customer_growth/test_flow.py tests/customer_growth/test_service_preferences.py`
- `node --check apps/guest-web/member/app.js && node --check apps/staff-center/growth/app.js`
- Chrome宽度390与1365的静态浏览器渲染与导航检查；前后端脚本无客户可见测试入口。
- 必需回归：重复微信身份注册返回相同customer_id、无有效邀请入店队列、不同门店不可互查、员工不得自证本人优惠、顾客关闭偏好授权即时生效、POS链接两分钟失效、真实订单退款只记不可变冲正、已承诺佣金不能随版本更改追溯重算。
