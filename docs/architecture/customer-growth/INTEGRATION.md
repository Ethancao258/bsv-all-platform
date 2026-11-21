# BSV ALL｜客户注册、员工认领、签名母版 V1｜集成交接

## 状态与结论

- `ISOLATED_TESTED`：自助注册、邀请码自动归因、店码待认领、员工认领+签名母版、客户确认、首笔真实事件模拟、会员权益候选账本、一次性预占/核销、动态佣金候选、退款更新、审计记录。
- `NOT_DEPLOYED`：生产腾讯云部署、CloudBase G0真实schema、微信AppID/回调域名验证、手机号验证码、支付宝认证、正式电子合同签署、财务工资核算、真实门店支付回调、客户个人数据主体权利处理的工单闭环。
- **不得直接将隔离测试库迁移到实际客户主库，也不得按孤立POS的模拟结算付款。**

## 对接层与数据所有者

| 现有主域 | 现有稳定ID | 新模块只做什么 |
|---|---|---|
| `organization` | `legal_entity_id,store_id,org_unit_id` | 校验门店法人归属，保留门店来源；不新建店表 |
| `workforce/identity_access` | `tr_code,employee_id,auth_subject_id` | 利用 TR→EMP→BM 认证与岗位授权；签名母版应在workforce权威域落库 |
| `customer` | `customer_id,loyalty_account_id,consent_id` | 会员唯一身份/隐私授权/会员周期/权益；目前candidate schema不能直接执行 |
| `marketing` | `touchpoint_id,attribution_id` | 归因证据、现场认领、纠错和推广码 |
| `commerce/payments` | `order_id,payment_event_id,refund_id` | 通过受信支付/退款事件确认消费；现有模拟POS不等于实际资金到账 |
| `operating_finance` | `payroll_run_id,settlement_id` | 输出候选佣金事件，真实应付工资需合同/任职/资格核验 |
| `event_audit` | `audit_event_id` | 各项签署、授权和归因变更做可追加审计 |

GitHub目标为 `Ethancao258/bsv-all-platform`。已有 `design/v4-2-r3-2-ux-v2-2` 分支有真正的人员身份A、POS staging与员工工作台。PR #17/#18为依赖叠加Draft，**不要直接覆盖它们的代码、部署、或合并到 main**。先创建功能分支，内容放在原有 14 个一级目录内。与正在进行的身份授权项目合并时，必须完成一次真实数据契约核对。

## 页面与API

- **客户端：** `/member/`，源文件 `apps/guest-web/member/`，作为电子菜单的会员入口。两条注册来源：带 employee invite token 的专属二维码，或者只含 `store_id` 的纸质门店二维码。会员身份认证默认微信 `snsapi_base`，仅拿 openid；不要求昵称/头像。生产需通过运营者公众号域名、HTTPS配置并完善正式隐私说明。
- **员工端：** `/staff/growth/`，源文件 `apps/staff-center/growth/`。登录后使用集团原身份 `GET /api/v1/identity/me` + 有效 `marketing.task.write` 门店Grant。看待认领客户临时码、个人推广码、签名母版、佣金规则。不能查看全体顾客手机号。
- **服务端：** `services/api/customer_growth/app.py`。逻辑接入既有受控API层，开发模式可在 loopback `8767` 独立运行，正式应使用受控网关，不要额外建立公开的第二个身份系统。
- **签名：** 只保存不可公开的签名样式，旧版本不可无痕覆盖；每次认领以已认证操作与政策版本留痕。正式合同仍必须走逐份本人确认、文件哈希和可靠电子签名机制，复用图片本身不是法律上自动完成签署。

## 典型完整路径

1. 印刷卡背面使用门店通用二维码 `https://已核准网站/member/?store_id=BSVS`；扫码是来源标识，不是实际到店证明。
2. 客户进入授权网页，核验身份，确认隐私告知，生成唯一 `customer_id`，且存放在`customer`权威域。重复访问应回到已有ID。
3. 通过员工专属码进入的客户自动记录预归因；扫通用门店码的客户产生有效期24h的待认领票据。
4. 员工用授权员工中心申请认领；客户本人确认后才写入有效待付款归因；已有线上归因不可抢占。
5. 真实订单完成并由受信服务核实到账后，转换会员与开发归因状态；对符合政策的订单产生候选佣金。禁止直接将模拟 `payment_verified=False` 推进真实财务。
6. 有效的返场权益显示在客户账户，纸卡只是提醒。首次付款激活两种候选权益（仅isolated演练）。真正的结账折扣由可信收银端先预占（10分钟），已验证的订单支付之后才能最终标记核销；多卡不增加权益。
7. 同一客户跨店付款，归因历史保持，基准佣金率由发生消费的门店当时政策决定。客户现有服务人和原始开发人可不同。
8. 离职、人事状态、合同政策、组织上级链、跨法人商户：待读取真实权威服务后才能产生可支付结算；候选佣金必须维持 `PROVISIONAL_NOT_PAYABLE`。

## 严格阻断的未知事项

- **CloudBase G0/G1**：确认真实当前10张产品表及相关客户/员工/门店表与索引、数据库权限、备份恢复。此 demo `*_candidate` 是测试模型，不是正式迁移SQL。
- **员工身份签名**：目前 `/api/v1/identity/me` 返回 `display_label` 而非可靠的法定姓名。生产签名母版接口主动阻断，需先接入HR经核实姓名；不应把艺名/昵称当作法律签名。
- **真正的付款**：现有 staging POS `services/api/bsv1/app.py` 返回 `payment_verified=False`。支付桥需对持牌支付服务商回调验签、对账、关联 `customer_id,store_id,order_id`，并将精确支付、退款事实送至签名内部事件接口。
- **原始上级链**：目前示意字段未对组织权威做时间快照；离职逐级承接及尾佣自动判断仍待连接真实组织任职数据；不得把空数组当成已记录上级。
- **会员权益**：实际政策、赠饮活动限制、历史有效卡承诺和优惠叠加条件必须审定，才能和主POS/外部平台核销关联。
- **外部渠道**：微信提供登录入口；短信需真实腾讯云SMS签名/模板/风控后另接模块，支付宝 OAuth、微信小程序和跨店合作商户身份连接先保留适配边界，**当前并未接通**。
- **安全**：隔离 demo登录必须只能运行于loopback，所有互联网入口需TLS/ICP备案、同源/CSRF、防刷验证码、IP限流、日志去标识化、密码/密钥独立托管、恢复演练及隐私政策正式发布。

## 代码测试

从工程根目录执行 `python -m pytest -q tests/customer_growth/test_flow.py`。可启动隔离 demo：`bash scripts/run_growth_isolated.sh`，再在本机打开 `http://127.0.0.1:8767/member/?store_id=BSVS` 和 `/staff/growth/`。

**上线闸门：真实会员身份、真实身份授权、真实门店订单、真实支付回调、主表迁移、权益核销、钱包发薪、签名法定姓名、审计/隐私和隔离恢复必须逐项通过。** 不得把本次 isolated PASS 作为生产部署成功。
