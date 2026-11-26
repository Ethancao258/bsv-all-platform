# CX-WP-E｜推荐归因、佣金政策及服务关系
状态 DESIGN_ONLY；独立研究与执行任务书。
业务编号：CX-11、CX-30。
模块：REFERRAL、COMMISSION。
候选专属路径：services/api/customer_growth/cx_referral/、apps/staff-center/growth/cx-referral/、tests/cx/E/（开工时与实际路径/既有owner核对，必要时集成人一次性调整）。
数据域：marketing、operating_finance、customer、workforce；既有数据所有权不改变。
操作编号：cx.referral.claim.v1、cx.commission.accrue.v1、cx.commission.reverse.v1、cx.commission.eligible.v1。
联调依赖：A、B、F、H；开发可立即使用冻结fixture。
生产门槛：合同税务审核、可信支付/履约、重复归因与退款对账。

## 研究与最短实现
复用 customer_growth 的 staff invite/claims、public confirm、HQ commission-policy 与 attribution-corrections，原有 employee_id/TR只引用。分离原始推荐人、当前服务负责人、佣金受益人；普通顾客可分享推荐码，现金推广需自愿资格、协议及核验。候选来源与已确认归因分开，使用有期限签名邀请、真实到店/客户确认，原归因不可被新链接覆盖；更正需审计。普通客户直接一层真实消费计酬，无入门费、无注册人数奖、无下线层级抽佣。现有员工规则不由CX修改。
佣金=合格净实收×已冻结政策费率×合同阶段系数，整数分/明确舍入；政策按租户、法人、资格、商品、归因期、时间版本管理。唯一键(order,beneficiary,policy,component)，只接受H验证支付+F履约事实；demo checkout不计。退款产生冲正而非修改历史；待结算/可付/已付/冲正分别记录。24h可作为最低待结算时间并由合同与风控调整，不是退款期限。H负责实际付款与财务核对；E不调用资金API。联系服务归属与隐私授权独立，客户不因员工离职失去资产。
## 验收
重复/自荐/伪造支付/多推荐/跨租户拒绝，政策变更不重算历史，退款部分或全额、员工离职后归属、已付后退款均有审计。未真实支付/合同/税务确认时佣金保持PROVISIONAL_NOT_PAYABLE。

## 全员通用执行指令
只领取本工作包；从集成人发布的同一不可变集成基线创建独立 Git worktree/分支，使用合成数据、隔离数据库与测试替身。先比对现有模块是否已有可复用函数，禁止重写。可在未获供应商授权时写契约测试、离线实现；不得声称真实接通。不得读取或修改其他Agent工作区、运行目录、共享数据库、端口、systemd、Nginx或生产资料。共享入口、数据字典、迁移登记、注册表、POS文件由集成人或既有POS负责人唯一写入；提交最小补丁请求。契约变更必须先冻结新版本并通知依赖方，不得单方面改变语义。
交付：变更文件清单、复用证据、业务流程及算法、测试结果（PASS/FAIL/MOCK_ONLY/NOT_RUN）、契约版本、迁移候选、回退、未解阻断、PR/SHA；不做部署。缺少真实授权时标 BLOCKED_LIVE，其他合成任务继续。禁用模块不得删除历史资产或重试未知资金交易。任何真实数据、密钥、商户凭证、私人经营政策不得提交Git。
