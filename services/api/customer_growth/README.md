# BSV1｜客户注册与员工认领 vertical slice

该目录提供两网页+后端数据库闭环。**仅隔离模式允许自动 `create_all`**；生产模式必须先完成 CloudBase G0/G1、旧会员去重、统一主数据映射与官方迁移。不得将 `bsv_growth_customer_candidate` 作为已有生产客户主档的替代品。

## 本地运行（虚构数据）

```bash
export BSV_GROWTH_ENV=isolated
export BSV_GROWTH_DB_URL=sqlite:////tmp/bsv-growth-demo.sqlite3
export BSV_GROWTH_SIGNING_KEY='ISOLATED-NOT-SECRET-123456789012345678901'
export BSV_GROWTH_PAYMENT_SIGNING_KEY='ISOLATED-PAYMENT-EVENT-SIGNING-KEY-9876543210'
python3 -m uvicorn services.api.customer_growth.app:app --host 127.0.0.1 --port 8767
```

访问 `/member/?store_id=BSVS` 和 `/staff/growth/`。员工用虚构身份登录、录入签名母版、生成邀请；客户使用本地演练身份登录、注册、认领确认。**模拟支付不会创建真正的应付工资**，只产生 `PROVISIONAL_NOT_PAYABLE` 账本投影。

## 生产门槛

- `BSV_GROWTH_ENV=production`；需独立PG DSN、公司真实门店目录、人员身份内部只读接口、密钥与同源域名。
- 现有POS V2.9测试结算始终是 `payment_verified=False`，禁止用其作为此服务的 `PAID` 事件。支付桥只能由经核验的支付渠道对账服务发起带签名事件。
- 真实员工使用集团登录会话，经 `/api/v1/identity/me` 验证 `marketing.task.write` 和合法实体及门店授权；签名母版的最终数据归 `workforce/identity_access` 管理，而非营销模块自行成为独立主库。
- 真实会员ID只允许集团 `customer` owner 发放；如果已有 `customer_id` 表或schema，需设计适配迁移，不能直接执行本demo DDL。
- 微信公众号网页授权需要已配置的AppID、Secret、网页授权域名、HTTPS回调。微信openid是单公众号范围的稳定认证主体，不要当公司跨渠道全局身份；后续手机号/支付宝认证需经过安全链接和身份去重，不允许仅凭昵称合并。
- 必须发布实际会员隐私告知、权限行使渠道、返场权益版本。第一次经验证付款后只是候选会员激活；具体一次性赠饮/折扣的生成与核销仍待对接`customer`权威权益账本，禁止凭纸卡兑奖。
- POS活动事件、原始开发链及财务不可无痕覆盖；冲突交总部纠错。正式合同签署必须另用可靠电子签名服务，签名母版图片不能代替当次签署。
- 配置实时服务限流、微信回调状态消费、网关私网限制、TLS、日志脱敏、备份恢复、用户数据删除与授权撤回流程，方可发布公网。

## API

- `GET /api/v1/growth/public/config`、`/auth/wechat/start`、`/auth/wechat/callback`、`POST /public/register`、`GET /public/me`
- `GET /staff/me`、`POST /staff/signature`、`POST /staff/invite`、`GET /staff/queue`、`POST /staff/claims`
- `GET /public/claim-requests`、`POST /public/claims/{id}/confirm`
- `POST /internal/payment-event` (独立支付签名、禁止公网匿名调用)、`POST /hq/commission-policy`

具体JSON schema见隔离环境 `/growth/docs`。未经真实身份来源和支付来源验证，不得宣称生产上线。
