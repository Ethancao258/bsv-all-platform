# CX-WP-B｜ACCWX与客户身份、会员、隐私
状态 DESIGN_ONLY；独立研究与执行任务书。
业务编号：CX-03、CX-18、CX-31。
模块：ACCWX、CUSPROFILE、MEMBER、CXGUARD。
候选专属路径：services/api/customer_growth/cx_auth/、apps/guest-web/member/cx-auth/、integrations/auth/cx/、tests/cx/B/（开工时与实际路径/既有owner核对，必要时集成人一次性调整）。
数据域：customer、identity_access、compliance；既有数据所有权不改变。
操作编号：cx.auth.login.v1、cx.customer.me.v1、cx.customer.bind.v1、cx.customer.age.v1。
联调依赖：A；开发可立即使用冻结fixture。
生产门槛：真实身份源、微信/短信授权、隐私与年龄核验。

## 研究与最短实现
复用现有 customer_growth 的 /auth/wechat/start、callback、/public/register、/public/me、/public/taste、/public/pos-link、营销授权与删除申请、既有 member 页面。ACCWX只增加短信/身份映射适配，不发第二套客户主码，不把 TR/EMP/BM 当顾客ID。先核对现有认证服务/CloudBase auth 与客户业务记录，微信官方OAuth/小程序登录视入口采用适当流程；短信腾讯云官方SDK、验证码模板审核，验证码单次使用、短TTL、次数限制、IP/账号限流、哈希保存，不记录明文。微信 state/防CSRF、服务端换码，OpenID 按 appid 隔离，UnionID 仅在具备可信条件时使用；两端身份通过双重证明绑定，冲突人工处理，不按昵称或手机号文本盲合并。
游客可看菜单。资料自愿填写，性别生日头像可空，必要环节才实名认证；优先保存核验结果而不是身份证影像。年龄声明、年龄核验分开；酒吧禁止未成年人入场，其他允许业态也禁止售酒给未成年人，疑问现场核验。修改年龄声明触发复核。客户/员工session audience、cookie作用域、路由权限隔离，服务端按主体查本人订单权益。累计折扣来自真实成交优惠快照，禁止虚构原价。注销撤销会话并依法保留财务资料。
## 验收
游客不登录可读菜单；微信/短信同自然人经验证绑定原客户；账号冲突、验证码重放、跨租户、客户访问员工/HQ、员工越权读取他人资料全部拒绝。无AppID/短信签名/真实客户主档时只做mock；不开放dev登录公网。回退禁用新登录方式，旧会员/交易不删除。

## 全员通用执行指令
只领取本工作包；从集成人发布的同一不可变集成基线创建独立 Git worktree/分支，使用合成数据、隔离数据库与测试替身。先比对现有模块是否已有可复用函数，禁止重写。可在未获供应商授权时写契约测试、离线实现；不得声称真实接通。不得读取或修改其他Agent工作区、运行目录、共享数据库、端口、systemd、Nginx或生产资料。共享入口、数据字典、迁移登记、注册表、POS文件由集成人或既有POS负责人唯一写入；提交最小补丁请求。契约变更必须先冻结新版本并通知依赖方，不得单方面改变语义。
交付：变更文件清单、复用证据、业务流程及算法、测试结果（PASS/FAIL/MOCK_ONLY/NOT_RUN）、契约版本、迁移候选、回退、未解阻断、PR/SHA；不做部署。缺少真实授权时标 BLOCKED_LIVE，其他合成任务继续。禁用模块不得删除历史资产或重试未知资金交易。任何真实数据、密钥、商户凭证、私人经营政策不得提交Git。
