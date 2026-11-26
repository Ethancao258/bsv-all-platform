# BSV ALL CX V1.3 实施级研究基线
本文件为建议实施规格，不是代码、已上线接口或真实配置。上版V1.1/1.2历史保留；本版细化优先，现行已批准契约/源码约束优先于设计假定。执行者先对照最新主机基线及既有owner，原表/接口可复用即映射，不另建同义实体。只使用专属worktree和合成测试数据库，不直接改部署目录。局部更优方案不破坏契约可记录后采用；跨组、数据归属、资金语义变更提交ADR，由集成人一次冻结。所有外部账号/密钥/报价/门店映射未核验项保留null，绝不能猜测或写入Git。
## 结论
不另建平台、不新增八个长期服务；按现有模块化单体/既有服务边界运行。A的URA解析、业务域政策、F/POS订单、D非现金资产、E应付、H资金、G第三方事实各一个写owner。禁止公共API网关成为第二业务引擎。已有V1.2 192项功能仍保留，新增操作解决缺口而不是增加产品范围。新编号为候选，集成人一次确认现有路径/类型映射。
## 开工入口
先读本README、CONTRACT-V1.3.md、OPERATIONS.json、STATES.json、PROVIDER-TEMPLATE.json、INDUSTRY-PROFILES.json、ACCEPTANCE.json，再读本人A-H.md与前版原任务书/URA/LEGACY-AUDIT/FEATURES。所有spec文件不包含可执行代码。每包内步骤按依赖排序，S0先复用核查，S1合成闭环，S2契约联调，S3获准实际业务验收；允许八组独立开发但共享文件只由集成人修改。旧POS热升级继续。
## 交付切片
R0 A最小解析器/两租户隔离；C可提前做只读菜单。R1 C菜单与B登录/会员；R2 D返场权益与E归因候选；R3 F受限POS接单；R4 G人工或实际获权核销；R5 H真实收款退款、F履约与D/E结算；R6存酒/计时/预约/商城及获准储值和付款，独立先完成的模块允许提前验收。此为依赖顺序，不是工时承诺。真实支付和核销授权不阻塞mock。
## 跨组事件与循环解除
F.order.created/fulfilled -> H确认支付/平台结算 -> E应付；H付款成功 -> E更新已付款投影。D预占由F报价/订单请求，H成功及F履约条件满足后确认，未知不释放；H商城支付触发D发券。G核销成功 -> F.external_fulfill -> H平台结算核实 -> E。事件唯一event_id+tenant，outbox与事实同事务；消费端inbox去重。不存在D/E/H启动依赖循环；不共享数据库跨域写入。F和现有POS owner合并受控桥；其他Agent不能改POS app.py。
## 验收与进度
保留V1.2 FEATURES.md的192项编号。ACCEPTANCE.json提供具体关键样例（尚未执行），不是192项均已独立实现测试；每个PR须逐项标记其覆盖功能ID、真实证据、未完成原因和是否允许延期。每组报告当前SHA、复用位置、代码/测试路径、接口映射、fixture、迁移/回退、实际授权；不能将mock说成线上完成。集成人只对共享冲突开ADR；无冲突不重复复盘。
## 证据
官方OpenAPI https://spec.openapis.org/oas/v3.1 ，PG时间范围 https://www.postgresql.org/docs/17/rangetypes.html ，微信JSAPI https://pay.wechatpay.cn/doc/v3/merchant/4012791870 ，腾讯云SendSms https://cloud.tencent.com/document/product/382/55981 ，收钱吧开放平台 https://doc.shouqianba.com/docs-for-smart/ 。收钱吧多份核销、部分撤销和结果查询字段见G，需以商户授权联调为准；不宣称已开通。旧代码证据来自V1.2审计所列历史SHA，未重新读取生产主机。专家为模拟审核视角。
