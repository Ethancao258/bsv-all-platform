# CX-WP-B V1.4 | ACCWX认证
This is implementation advice, not a mandatory procedure. Use actual host findings to improve it. No live code or activation.
## Route and evidence
复用现有微信OAuth及自有账户映射，腾讯云短信SDK发送+自有挑战校验。
Alternative: CloudBase身份认证：微信登录+短信验证码登录+bindWithProvider等官方账号关联能力，BSV只保留业务customer_id映射。
托管身份减少验证码/会话研发；官方管理登录文档提示手机号验证码登录地域限制（上海），故不能假设现有环境可开通。
Adopt if: 确认现有环境地域、价格/配额、租户隔离、服务端令牌校验、存量账户迁移、微信/短信绑定及出口；若实机复用总代码与维护明显更少且全部通过，采用托管；否则首选。
Sources: https://docs.cloudbase.net/authentication-v2/method/wechat-login ; https://docs.cloudbase.net/authentication-v2/method/sms-login ; https://docs.cloudbase.net/authentication-v2/auth/manage-login ; https://docs.cloudbase.net/authentication-v2/auth/introduce
## Concrete execution recommendation
游客直接看菜单；登录取得verified issuer+subject，唯一查映射→返回旧customer或待注册proof；注册明确隐私告知后事务写customer+identity；两个有效证明才能绑定；身份冲突转恢复待办。SMS challenge发送/验证分离，验证码MAC、一次性、尝试/发送限额；手机号回收不自动接管。
## New/revised operations
- cx.auth.login.v1: provider:s,proof_ref:id → session_ref:id,customer_id:id?,status:s; 会话通过受保护cookie/渠道凭证交付
- cx.customer.me.v1: (empty) → customer_id:id,member_status:s,profile:obj; 只读本人
- cx.customer.bind.v1: proof_a:id,proof_b:id → customer_id:id,binding_status:s; 双证明新鲜且一次性
- cx.customer.age.v1: declared_adult:b → declaration_state:s,verification_state:s; 声明不等于现场核验
- cx.auth.challenge.send.v1: phone:s,purpose:s → challenge_id:id,expires_at:t; 不泄露号码是否存在；限频
- cx.auth.challenge.verify.v1: challenge_id:id,code:s → proof_ref:id,expires_at:t; 一次性，限尝试
- cx.customer.profile.update.v1: patch:obj,expected_revision:id → profile:obj,revision:id; 允许字段白名单，不允许自行改核验状态
- cx.customer.consent.update.v1: purpose:s,accepted:b,notice_version:id → receipt_id:id; 撤回传播到通知，保留合法记录
- cx.customer.recovery.request.v1: proof_ref:id,reason:s → case_id:id,state:s; 防账户接管，不自动合并
- cx.customer.history.summary.v1: cursor:s? → orders:objs,total_discount_minor:i?,next_cursor:s?; 缺可靠优惠基准时省略合计，禁止以零或虚构原价替代
- cx.member.code.issue.v1: store_id:id? → proof_ref:id,expires_at:t; 短期用途绑定，非支付码
- cx.customer.age.verify.v1: customer_id:id,method:s,result:s → verification_ref:id,state:s; 授权员工现场核验，仅留必要证据
- cx.customer.close.request.v1: proof_ref:id → case_id:id,state:s; 撤销会话与合法留存分开
- cx.customer.register.v1: proof_ref:id,notice_version:id,consent_accepted:b,display_name:s? → customer_id:id,member_status:s; 核验认证证明、唯一身份；重复注册返回原主码
- cx.member.card.bind.v1: card_proof_ref:id → binding_id:id,state:s; 纸卡仅定位已签发权益，不凭二维码发放
- cx.customer.privacy.request.v1: kind:s,proof_ref:id → case_id:id,state:s; 查询/更正/删除请求，依法保留必要记录
## Deliverable and tests
Read FEATURE-TRACE filtered by accountable_owner and CRITICAL-CASES. Related-only entries need explicit UI/domain work, not false pass. Preserve old code when equivalent. Actual paths and schema mapping validated on host; missing binding null. Compare alternatives using observed implementation effort and recurring fee, authorization, error recovery and rollback. No claim of global best. 
## V1.3 inherited scope (historical, signatures superseded above)
# CX-WP-B｜ACCWX与会员 V1.3
本文件为建议实施规格，不是代码、已上线接口或真实配置。上版V1.1/1.2历史保留；本版细化优先，现行已批准契约/源码约束优先于设计假定。执行者先对照最新主机基线及既有owner，原表/接口可复用即映射，不另建同义实体。只使用专属worktree和合成测试数据库，不直接改部署目录。局部更优方案不破坏契约可记录后采用；跨组、数据归属、资金语义变更提交ADR，由集成人一次冻结。所有外部账号/密钥/报价/门店映射未核验项保留null，绝不能猜测或写入Git。

## 数据模型（候选映射）
IdentityLink(tenant,provider,issuer,subject_digest,customer_id,verified_at,status) unique; AuthChallenge(id,purpose,phone_digest,code_mac,expires_at,attempts,state); CustomerProfile(existing customer_id,optional_fields,revision); ConsentReceipt(customer_id,purpose,notice_version,decision,at); AgeEvidence(declaration,verification_state,staff_ref,at). 旧Customer主码不变。

## 界面与业务动作
游客菜单→主动登录→微信或短信→原账号识别/绑定冲突→个人中心；首次首访资格显示待激活/已激活。资料页、隐私授权、动态会员码、历史优惠；年龄声明与员工核验分开。

## 可执行工作顺序
B-01. 复用现有OAuth state、register/me、member；查现有身份schema与唯一键，先生成重复/冲突报告
B-02. 微信H5与小程序分适配；现有认证可复用则不购买新服务；腾讯云SendSms只发送，OTP自有校验或经已获授权身份服务验证
B-03. 验证码挑战MAC、TTL、限频、最大尝试、单次消耗；未配置短信渠道禁用而非模拟成功
B-04. 双证明绑定；号码换绑、账号恢复人工流程；客户/员工/HQ会话隔离；首访激活引用D/F真实规则
B-05. 提供个人资料/授权/注销/动态会员码；高风险实名需明确用途及授权，留核验结果非原始影像；年龄存声明+员工核验

