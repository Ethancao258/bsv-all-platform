# CX-WP-B｜身份与会员
共同研发建议，不是强制步骤；MUST见ARCHITECTURE；局部等效优化可直接采用。初始只读START-HERE、本文件及公共ARCHITECTURE；按需查INDEX，不重复读历史。
## Route and evidence
复用现有微信OAuth及自有账户映射，腾讯云短信SDK发送+自有挑战校验。
Alternative: CloudBase身份认证：微信登录+短信验证码登录+bindWithProvider等官方账号关联能力，BSV只保留业务customer_id映射。
托管身份减少验证码/会话研发；官方管理登录文档提示手机号验证码登录地域限制（上海），故不能假设现有环境可开通。
Adopt if: 确认现有环境地域、价格/配额、租户隔离、服务端令牌校验、存量账户迁移、微信/短信绑定及出口；若实机复用总代码与维护明显更少且全部通过，采用托管；否则首选。
Sources: https://docs.cloudbase.net/authentication-v2/method/wechat-login ; https://docs.cloudbase.net/authentication-v2/method/sms-login ; https://docs.cloudbase.net/authentication-v2/auth/manage-login ; https://docs.cloudbase.net/authentication-v2/auth/introduce
## Concrete execution recommendation
游客直接看菜单；登录取得verified issuer+subject，唯一查映射→返回旧customer或待注册proof；注册明确隐私告知后事务写customer+identity；两个有效证明才能绑定；身份冲突转恢复待办。SMS challenge发送/验证分离，验证码MAC、一次性、尝试/发送限额；手机号回收不自动接管。

## 最小可交付切片
游客→验证主体→原客户或注册证明→注册/双证绑定→会员码/资料/授权；年龄核验、冲突恢复。
## 真实复用证据（历史SHA，运行态未知）
services/api/customer_growth/app.py:107–158 Customer/CustomerIdentity/BrowserSession/OAuthState — reuse candidate; issuer/tenant uniqueness, conflict scan
services/api/customer_growth/app.py:514–657 wechat_start/wechat_callback/register/guest_me — reuse candidate; no duplicate customer ID
services/api/customer_growth/app.py:1261–1307 marketing_preference/delete_request/member_page/member_privacy — reuse candidate; consent/privacy
## 所属代码及业务对象
现有客户增长认证/会员组件；不改员工主身份权限

IdentityLink(tenant,provider,issuer,subject_digest,customer_id,verified_at,status) unique; AuthChallenge(id,purpose,phone_digest,code_mac,expires_at,attempts,state); CustomerProfile(existing customer_id,optional_fields,revision); ConsentReceipt(customer_id,purpose,notice_version,decision,at); AgeEvidence(declaration,verification_state,staff_ref,at). 旧Customer主码不变。

## 界面与业务动作
游客菜单→主动登录→微信或短信→原账号识别/绑定冲突→个人中心；首次首访资格显示待激活/已激活。资料页、隐私授权、动态会员码、历史优惠；年龄声明与员工核验分开。


## 界面与验收
页面：B-MEMBER、B-LOGIN、B-PROFILE。复用三端壳，UI/PAGES与DESIGN按需查；本组18项功能按accountable_owner过滤FEATURE-TRACE，操作按owner查INDEX，必要时与delivery_owner合作；schema使用唯一CONTRACTS文件，不逐个创建HTTP。按合成FIXTURES/CASES测试，真实配置留空，外部授权未取得不假装可用。对真实运行路径不明项先只读核实。
## 可直接复制的启动指令
领取CX-WP-B。从总集成人确认的共同开发基线及独立worktree读取START-HERE、ARCHITECTURE、本任务书。选择现有代码复用、首选、备选或更短等效路径，记录证据；按最小切片实现和测试。只改本组文件；共享文件、迁移及POS由真实owner协调。未获授权标BLOCKED_LIVE，使用合成fixture继续开发；不改运行目录、不未经审批部署。交付SHA、功能ID、测试证据、阻断与回退。局部优化无需反复申请。