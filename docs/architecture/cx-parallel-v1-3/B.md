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

## 操作合同
- cx.auth.login.v1: provider:s,proof_ref:id → session_ref:id,customer_id:id?,status:s；会话通过受保护cookie/渠道凭证交付
- cx.customer.me.v1: (empty) → customer_id:id,member_status:s,profile:obj；只读本人
- cx.customer.bind.v1: proof_a:id,proof_b:id → customer_id:id,binding_status:s；双证明新鲜且一次性
- cx.customer.age.v1: declared_adult:b → declaration_state:s,verification_state:s；声明不等于现场核验
- cx.auth.challenge.send.v1: phone:s,purpose:s → challenge_id:id,expires_at:t；不泄露号码是否存在；限频
- cx.auth.challenge.verify.v1: challenge_id:id,code:s → proof_ref:id,expires_at:t；一次性，限尝试
- cx.customer.profile.update.v1: patch:obj,expected_revision:id → profile:obj,revision:id；允许字段白名单，不允许自行改核验状态
- cx.customer.consent.update.v1: purpose:s,accepted:b,notice_version:id → receipt_id:id；撤回传播到通知，保留合法记录
- cx.customer.recovery.request.v1: proof_ref:id,reason:s → case_id:id,state:s；防账户接管，不自动合并
- cx.customer.history.summary.v1: cursor:s? → orders:objs,total_discount_minor:i,next_cursor:s?；F/H事实投影；不虚构原价
- cx.member.code.issue.v1: store_id:id? → proof_ref:id,expires_at:t；短期用途绑定，非支付码
- cx.customer.age.verify.v1: customer_id:id,method:s,result:s → verification_ref:id,state:s；授权员工现场核验，仅留必要证据
- cx.customer.close.request.v1: proof_ref:id → case_id:id,state:s；撤销会话与合法留存分开

## 验收样例（尚未运行）
|ID|前置/操作|预期|
|---|---|---|
|B01|重复注册同issuer与subject|返回原客户ID|
|B02|不同appid同subject|不自动合并|
|B03|短信过期/重放/错误次数达限|拒绝并不泄露是否已注册|
|B04|客户调用员工接口|403或等效拒绝|
|B05|未成年人声明/年龄存疑|酒吧不准入，非酒精合法业态按规则|
|B06|撤销营销授权|停止后续营销，不删除法定账务|

## 交付
身份映射与会员API、授权状态、手机端流程、既有用户兼容测试；微信/短信真授权待填。
