# CX-WP-B｜ACCWX与客户身份、会员、隐私 V1.2
状态：DESIGN_READY，非已实现、非已部署。阅读上版 ../cx-parallel-v1-1/README.md、CONTRACT.md、REGISTRY.json 及对应任务书；本版增量补充，冲突以本版设计建议为准，既有 AGENTS.md 与已批准正式契约优先。源码证据基线 2052ef51f011be3c5898d816932d8982f420b752；最新主机状态须由集成人复核。所有路径/表/字段为拟议映射，不是已创建对象。

业务范围：CX-03、CX-18、CX-31；旧模块编号与候选路径保留：services/api/customer_growth/cx_auth/、apps/guest-web/member/cx-auth/、integrations/auth/cx/、tests/cx/B/。功能逐项索引见 FEATURES.md；新增操作见 OPERATIONS.json。

## 决策与备选
现有 customer_growth/app.py 已有 OAuth state 单次消费、wechat start/callback、register/me/taste、现有会员UI；sms_enabled=False，现有身份映射为(provider,subject_hash)。首选抽取现有微信OAuth为 adapter，增加短信adapter；若现有CloudBase认证服务可真实满足微信/短信、租户隔离、账户关联及授权，应优先用它，不并建认证服务。H5/公众号OAuth与小程序code2Session不同协议，按渠道适配，不混用OpenID。腾讯云SendSms只负责发送，不能代替业务验证。
## 实现顺序
B1 复用现有customer_id及登录cookie/会话，先验证已有schema和候选数据归属；身份键扩为租户+provider+issuer/appid+subject_hash，保留旧映射；迁移候选先检测冲突，不自动合并。B2 微信adapter通过URA引用固定官方操作，state绑定租户、回跳域、入口和设备cookie，一次使用；服务端交换code、验证返回与issuer，失效重新登录。B3 SMS adapter 用官方SDK，单次短TTL验证码的HMAC摘要、限频与失败计数、发送与验证分离、错误信息避免枚举账号；备用短信供应商使用同一验证挑战、不重复发码，需限时并受成本上限；默认TTL/频次为可验证测试参数而非政策。B4 双身份绑定需两侧新鲜证明；已绑其他客户时进入人工恢复，号码回收不能自动夺取旧账户；可撤销会话和绑定。B5 注册游客与首访会员资格分离，展示会员码/历史/累计折扣由权威订单投影计算；个人资料自愿，资料更正、授权、注销与营销撤回；生日/年龄/实名认证按用途最小化。B6 年龄声明与现场核验分开，门店业态准入策略引用，不允客户端直接授予售酒权；提现所需实名由合规支付或腾讯官方核验能力按需触发。
## 候选契约
auth.login/provider callback -> authenticated_subject scoped；customer.bind -> existing customer or conflict；customer.me -> authorized profile; customer.age -> declaration+verification_status；增加 challenge.send/verify、profile.update、consent.update、recovery.request、history.summary（操作名见 operations.json）。所有页面用客户会话scope，员工和HQ不共享权限。
## 验收
游客无需注册；同一身份重复注册结果唯一、不同appid同字符串不合并、微信/短信双证明绑定、短信重放/过期/暴力尝试拒绝；跨租户及客户访问员工财务拒绝；隐私撤回不删除法定记录；年龄自报改变触发复核。真实微信appid、域名与短信签名/模板授权未确认时mock。参考腾讯云SendSms及微信开放文档；不购买额外认证服务，除非实测更低总成本。

## 给腾讯云执行Agent的合作规则
本设计是当前证据下的首选路径，不是不可修改的命令。你负责实机复核、提出更短/更优方案及实施。若发现既有实现可直接复用、平台接口变更或冲突，不重复研发：提交一条变更提议（原方案、实际代码/官方证据、替代方案、节省的变更/维护量、影响契约/数据/风险、测试与回退）。不改变外部契约、不降低安全、不改变产品目标且不抢其他路径的局部优化，可在所属分支直接实施并记录；共享契约、财务语义、数据归属、生产发布、法律约束变更由集成人/负责人审定，一次广播新版本。反例有证据则修正规范，不要求Agent重复完整需求研究。
开发仅限独立worktree、合成fixture、指定路径。禁止改运行release、共享数据库、公开路由、他组文件、实际支付/核销或生产DDL。依赖未就绪时只用统一fixture；不自行实现依赖方的业务逻辑。输出步骤逐项PASS/FAIL/MOCK_ONLY/NOT_RUN、代码位置、证据、PR/SHA、配置/迁移影响、回退及实机未决门槛。
