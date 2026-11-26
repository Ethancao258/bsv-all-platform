# Source and decision register
V1.3 immutable baseline: https://github.com/Ethancao258/bsv-all-platform/tree/4f836347944facab42c431364739f6b0d7785c3f/docs/architecture/cx-parallel-v1-3/
Prior historical code inspection: ../cx-parallel-v1-2/LEGACY-AUDIT.md. No new production inspection.
## A URA与租户
- https://learn.microsoft.com/azure/architecture/patterns/external-configuration-store
- https://www.postgresql.org/docs/17/ddl-constraints.html
多个进程或企业需要统一配置、已有可靠PG时更合适；否则文件更短。Microsoft外部配置模式明确支持数据库作为后端。
同一变更同时供2个既有进程使用且文件方案无法一致刷新，或现有HQ已有配置管理可直接复用；双租户、恢复、回切均通过。单企业不为此强迁。
## B ACCWX认证
- https://docs.cloudbase.net/authentication-v2/method/wechat-login
- https://docs.cloudbase.net/authentication-v2/method/sms-login
- https://docs.cloudbase.net/authentication-v2/auth/manage-login
- https://docs.cloudbase.net/authentication-v2/auth/introduce
托管身份减少验证码/会话研发；官方管理登录文档提示手机号验证码登录地域限制（上海），故不能假设现有环境可开通。
确认现有环境地域、价格/配额、租户隔离、服务端令牌校验、存量账户迁移、微信/短信绑定及出口；若实机复用总代码与维护明显更少且全部通过，采用托管；否则首选。
## C 客户门户
- https://developer.meituan.com/isv/daocan/
- https://developer.meituan.com/docs/biz/biz_rms_e8a2bfb2-c855-40ff-8565-ee946a5cae2e
美团官方顾客点餐自助核销明确支持品牌微信小程序；当获权接口或支付/登录必须小程序时原生入口可能更短。
取得小程序主体/域名/支付/验券能力，H5不能合法提供关键功能，且实际扫码→点单/核销流程更短；否则不做双前端。
## D 权益与存酒
- https://www.postgresql.org/docs/17/sql-update.html
- https://www.postgresql.org/docs/17/dml-returning.html
- https://www.postgresql.org/docs/17/explicit-locking.html
PG17支持UPDATE RETURNING；单行条件更新可减少一次读锁往返。多资产组合仍需事务及固定锁顺序。
现有行锁实现简单可靠则保留；只有实际争用、性能或原子更新更易复用时采用条件更新；并发、重复、回滚、负余额、锁死均验证。
## E 推荐与佣金
- https://docs.camunda.io/docs/components/modeler/dmn/decision-table-hit-policy/
- https://docs.camunda.org/get-started/dmn/model/
规则组合复杂时可视化冲突检查更好；简单费率/阶段不值得额外引擎。Camunda文档明确UNIQUE不允许多条匹配。
实际存在大量互相交叉的政策条件、手工配置频繁冲突，且可用运行库、许可证、资源开销与同输入输出回归验证通过；否则保留SQL+类型化参数。
## F POS与消费服务
- https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html
- https://developer.meituan.com/docs/biz/biz_rms_e8a2bfb2-c855-40ff-8565-ee946a5cae2e
AWS事务发件箱模式解决业务提交与事件发送双写风险；仅使用现有数据库，消费者幂等，不需要AWS/Kafka。
POS负责人证明实际订单可原子提交，库存/年龄/权限/价格实时校验且重放无重复；自动接单试点失败率和人工纠错成本不高于人工确认，否则保持草稿。
## G 第三方核销
- https://doc.shouqianba.com/docs-for-smart/
- https://developer.meituan.com/isv/daocan/
- https://developer.open-douyin.com/docs/resource/zh-CN/local-life/develop/OpenAPI/general-capabilities/life.capacity.fulfilment/certificate.get
- https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/open-capacity/solutions/life-service-solutions/verification-tool
直接获得平台原生能力及独立退出路径；美团明确支持品牌小程序自助验券，抖音查询接口要求验券准备返回的encrypted_code，不能用明文替代。
聚合未获消费者自主核销或ISV授权、报价/异常恢复不合格，而平台直连实测可用；或业务量使维护净成本更低。若两边未授权，人工官方核销，不模拟真实成功。
## H 收款退款与资金
- https://doc.shouqianba.com/zh-cn/
- https://doc.shouqianba.com/zh-cn/api/sign.html
- https://doc.shouqianba.com/zh-cn/api/interface/refund.html
- https://pay.wechatpay.cn/doc/v3/merchant/4012791870
收钱吧官方支付接口与退款权限说明可验证；聚合减少接口数，但不证明适用于客户H5的支付方式、自动代付或企业转售。
确认实际线上场景、商户签约、支付/退款/查询及对账、授权费率、ISV许可；比较24个月费用、人工异常、独立故障域。不能提供真实代付时继续官方商家转账，不把聚合支付等同代付。
These official sources establish technical patterns/capabilities, not BSV authorization, economics, uptime or global optimality. Actual quotes/terms/region/SDK compatibility and host tests remain required. No independent human experts engaged.