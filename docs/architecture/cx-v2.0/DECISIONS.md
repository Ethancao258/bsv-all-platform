# Eight alternative implementation routes
## A URA与租户
Primary: 现有受保护配置文件/注册表 + 进程内解析器；活动指针原子替换，启动时加载已批准版本。
Alternative: 现有PostgreSQL配置表作为共享外部配置存储（无需新服务），配置变更事务提交+版本指针，实例按版本检查刷新。
Evidence: 多个进程或企业需要统一配置、已有可靠PG时更合适；否则文件更短。Microsoft外部配置模式明确支持数据库作为后端。
Adoption/reversal gate: 同一变更同时供2个既有进程使用且文件方案无法一致刷新，或现有HQ已有配置管理可直接复用；双租户、恢复、回切均通过。单企业不为此强迁。
References: https://learn.microsoft.com/azure/architecture/patterns/external-configuration-store ; https://www.postgresql.org/docs/17/ddl-constraints.html
Execution recommendation: 单一resolver输入可信tenant+ref+scope+as_of，读取active revision；按门店>法人>租户选择唯一候选，再校验权限/授权/feature/健康；不返回密钥。配置候选dry-run→批准→CAS→新操作读取新版本，旧操作继续旧binding。数据库路由的引导引用留在受控启动配置。审批同一人不得兼任高风险批准者。

## B ACCWX认证
Primary: 复用现有微信OAuth及自有账户映射，腾讯云短信SDK发送+自有挑战校验。
Alternative: CloudBase身份认证：微信登录+短信验证码登录+bindWithProvider等官方账号关联能力，BSV只保留业务customer_id映射。
Evidence: 托管身份减少验证码/会话研发；官方管理登录文档提示手机号验证码登录地域限制（上海），故不能假设现有环境可开通。
Adoption/reversal gate: 确认现有环境地域、价格/配额、租户隔离、服务端令牌校验、存量账户迁移、微信/短信绑定及出口；若实机复用总代码与维护明显更少且全部通过，采用托管；否则首选。
References: https://docs.cloudbase.net/authentication-v2/method/wechat-login ; https://docs.cloudbase.net/authentication-v2/method/sms-login ; https://docs.cloudbase.net/authentication-v2/auth/manage-login ; https://docs.cloudbase.net/authentication-v2/auth/introduce
Execution recommendation: 游客直接看菜单；登录取得verified issuer+subject，唯一查映射→返回旧customer或待注册proof；注册明确隐私告知后事务写customer+identity；两个有效证明才能绑定；身份冲突转恢复待办。SMS challenge发送/验证分离，验证码MAC、一次性、尝试/发送限额；手机号回收不自动接管。

## C 客户门户
Primary: 现有H5菜单与公开投影，保持原URL；按feature flag渲染，规则推荐。
Alternative: 官方微信小程序原生入口 + H5作为独立浏览器备用，仍使用同一后端操作契约；不复制商品、会员、订单库。
Evidence: 美团官方顾客点餐自助核销明确支持品牌微信小程序；当获权接口或支付/登录必须小程序时原生入口可能更短。
Adoption/reversal gate: 取得小程序主体/域名/支付/验券能力，H5不能合法提供关键功能，且实际扫码→点单/核销流程更短；否则不做双前端。
References: https://developer.meituan.com/isv/daocan/ ; https://developer.meituan.com/docs/biz/biz_rms_e8a2bfb2-c855-40ff-8565-ee946a5cae2e
Execution recommendation: 现有catalog发布投影→ETag/version→店别公开菜单。推荐硬过滤店别/可售/预算/酒精限制及明确过敏需求；tag Jaccard=交集/并集，预算匹配可配置；空偏好用编辑排序；分数同分按product_id稳定排序。过敏信息未知不得当安全；最终报价F。

## D 权益与存酒
Primary: 现有Benefit/Reservation行锁+唯一键+流水，同事务扣减。
Alternative: PostgreSQL条件UPDATE RETURNING/版本CAS，原子库存余额扣减+同事务插入流水和幂等记录；可用于高并发单资产，非另建账本。
Evidence: PG17支持UPDATE RETURNING；单行条件更新可减少一次读锁往返。多资产组合仍需事务及固定锁顺序。
Adoption/reversal gate: 现有行锁实现简单可靠则保留；只有实际争用、性能或原子更新更易复用时采用条件更新；并发、重复、回滚、负余额、锁死均验证。
References: https://www.postgresql.org/docs/17/sql-update.html ; https://www.postgresql.org/docs/17/dml-returning.html ; https://www.postgresql.org/docs/17/explicit-locking.html
Execution recommendation: 可用=已发行+调整-已消费-活动预占。预占唯一键（asset,quote,request）；锁资产、校验范围/时效/资格、扣可用+建hold；支付未知到期转REVIEW不释放。消耗与释放是互斥终态。存酒qty用最小单位；标签、员工、门店、expiry；到期进入待处置不删。计时区间按UTC取交集、暂停扣除，费率引用原版本，金额由F报价。

## E 推荐与佣金
Primary: 复用现有版本化政策表+类型化条件/费率计算，唯一规则解析，差额流水。
Alternative: DMN标准决策表（例如Camunda DMN UNIQUE hit policy）作为独立政策评估适配器；不替换佣金主账，不要求部署Camunda平台。
Evidence: 规则组合复杂时可视化冲突检查更好；简单费率/阶段不值得额外引擎。Camunda文档明确UNIQUE不允许多条匹配。
Adoption/reversal gate: 实际存在大量互相交叉的政策条件、手工配置频繁冲突，且可用运行库、许可证、资源开销与同输入输出回归验证通过；否则保留SQL+类型化参数。
References: https://docs.camunda.io/docs/components/modeler/dmn/decision-table-hit-policy/ ; https://docs.camunda.org/get-started/dmn/model/
Execution recommendation: 合格支付/结算减匹配退款；仅真实履约及已确认归因计佣。累计目标=round_half_up(net_minor×rate_bps×coeff_bps/1e8)，delta=target-已记。分配尾差按稳定line_id规则、总额守恒。以order/beneficiary/policy/component唯一聚合，事件去重；策略缺失只候选。H对账后更新应付状态，不调用资金接口。

## F POS与消费服务
Primary: 客户提交现有POS待确认草稿，员工接单；内部调用或现有受限HTTP，单一订单写源。
Alternative: POS原有写入事务 + transactional outbox/inbox 自动接单与异步履约投影；保留员工确认作为门店开关。
Evidence: AWS事务发件箱模式解决业务提交与事件发送双写风险；仅使用现有数据库，消费者幂等，不需要AWS/Kafka。
Adoption/reversal gate: POS负责人证明实际订单可原子提交，库存/年龄/权限/价格实时校验且重放无重复；自动接单试点失败率和人工纠错成本不高于人工确认，否则保持草稿。
References: https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html ; https://developer.meituan.com/docs/biz/biz_rms_e8a2bfb2-c855-40ff-8565-ee946a5cae2e
Execution recommendation: 静态桌码定位，短期join proof绑定tenant/store/visit/actor；结束撤权。quote服务端算并锁版本；submit按同幂等键同参数复用原order；员工accept按expected revision单写。预约半开区间冲突锁；队列单调序号；服务任务按权限状态更新。G事实写订单使用唯一external_fact_id，H支付结果只更新已核验事实。

## G 第三方核销
Primary: 收钱吧智慧经营聚合核销；人工官方端作为低风险备用。
Alternative: 美团官方顾客点餐自助核销 + 抖音官方券准备/核销/券状态查询两适配器。
Evidence: 直接获得平台原生能力及独立退出路径；美团明确支持品牌小程序自助验券，抖音查询接口要求验券准备返回的encrypted_code，不能用明文替代。
Adoption/reversal gate: 聚合未获消费者自主核销或ISV授权、报价/异常恢复不合格，而平台直连实测可用；或业务量使维护净成本更低。若两边未授权，人工官方核销，不模拟真实成功。
References: https://doc.shouqianba.com/docs-for-smart/ ; https://developer.meituan.com/isv/daocan/ ; https://developer.open-douyin.com/docs/resource/zh-CN/local-life/develop/OpenAPI/general-capabilities/life.capacity.fulfilment/certificate.get ; https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/open-capacity/solutions/life-service-solutions/verification-tool
Execution recommendation: 先查券/确认平台、门店、SKU与份数→持久化consume attempt和原binding/requestId→发送→原单查询→确认核销事实→F幂等补单。撤销必须针对具体consume_attempt，成功+在途撤销数量不得超已核销。业务状态与POS履约状态分开；H结算到账才算收入。

## H 收款退款与资金
Primary: 已有正规支付渠道，微信官方API v3+支付宝获权备用，H统一支付分配/回单/账本。
Alternative: 收钱吧统一支付Web API作为收款/退款适配器；原有直连或门店正规收款保留独立备用。
Evidence: 收钱吧官方支付接口与退款权限说明可验证；聚合减少接口数，但不证明适用于客户H5的支付方式、自动代付或企业转售。
Adoption/reversal gate: 确认实际线上场景、商户签约、支付/退款/查询及对账、授权费率、ISV许可；比较24个月费用、人工异常、独立故障域。不能提供真实代付时继续官方商家转账，不把聚合支付等同代付。
References: https://doc.shouqianba.com/zh-cn/ ; https://doc.shouqianba.com/zh-cn/api/sign.html ; https://doc.shouqianba.com/zh-cn/api/interface/refund.html ; https://pay.wechatpay.cn/doc/v3/merchant/4012791870
Execution recommendation: 锁order allocation，已确认+在途金额≤应收；持久化DISPATCHING before I/O，未知查原单，明确不可成功终态才释放并允许客户选备用。回调验签+原商户/金额/币种核对，去重。退款锁原支付累计成功+在途≤已付。预付本金、赠送、佣金负债分别记账；七日未兑付退款权及其他法定权利不缩短。E结算锁定后H付款，未知不解锁。

补充：CloudBase短信仍需短信供应商/签名模板且地域受限；https://docs.cloudbase.net/en/authentication-v2/auth/manage-login 。实际授权、费率、性能未知；24个月总成本=实施+运维+服务费+异常工时+退出迁移；无真实数据不宣称全局最优。