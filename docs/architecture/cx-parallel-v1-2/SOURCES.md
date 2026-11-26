# 可核实来源与使用限制（2026-11-26）
- GitHub源码基线： https://github.com/Ethancao258/bsv-all-platform/tree/2052ef51f011be3c5898d816932d8982f420b752 。读取了 customer_growth/app.py (1–110, 508–608, 995–1195), bsv_growth_pos.py, bsv_catalog_config.py, bsv_catalog_repository.py, supply/gateway.py, reference_adapter.py, identity_client.py 的相关区段；具体证据见 LEGACY-AUDIT.md。最新运行代码及原始主机报告未公开。
- 外部配置 https://learn.microsoft.com/azure/architecture/patterns/edge-workload-configuration ; 熔断 https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker ; 暂态故障 https://learn.microsoft.com/en-us/azure/well-architected/design-guides/handle-transient-faults 。借鉴设计模式，不要求采购Azure。
- 事务outbox https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html 。不要求AWS服务。
- PostgreSQL17 时间范围 https://www.postgresql.org/docs/17/rangetypes.html ; 锁 https://www.postgresql.org/docs/17/explicit-locking.html ; 约束 https://www.postgresql.org/docs/17/ddl-constraints.html 。
- 腾讯云短信 SendSms https://cloud.tencent.com/document/product/382/55981 ; Python SDK https://cloud.tencent.com/document/product/382/56059 。真实签名/模板/费用待核实；微信小程序官方原文未取得有效检索，需Agent核对适用渠道文档，不视为已接入。
- 收钱吧 https://doc.shouqianba.com/docs-for-smart/ ; 核销接口 https://doc.shouqianba.com/docs-for-smart/接口说明/团购券/核销.html ; 开通流程 https://doc.shouqianba.com/docs-for-smart/接口说明/团购券/开通流程.html 。查券30分钟、核销requestId 24h缓存、原requestId查结果是已查阅文档所示约束；真实权限、价格、ISV条款和接口测试待核实。
- 微信支付 JSAPI https://pay.wechatpay.cn/doc/v3/merchant/4012791870 ; 商家转账 https://pay.wechatpay.cn/doc/v3/merchant/4012715211 ; 佣金场景 https://pay.wechatpay.cn/doc/v3/merchant/4013774590 。
- 支付宝手机网站支付 https://developer.alibaba.com/docs/doc.htm?articleId=105287&docType=1&treeId=203 ; WebView兼容性提示 https://aipay.alipay.com/article/3923 。客户端、授权和最新接口需实测。
- 北京单用途预付卡条例 https://www.beijing.gov.cn/zhengce/dfxfg/202111/t20211130_2549001.html 第16/17条；七日未兑付退款法定权利不得被企业缩短。真实发行主体与适用规则待合规审核。
所有技术资料证明能力/约束，不证明BSV账户已获授权或全局经济最优；不复制第三方代码，不使用真实资金进行设计阶段测试。
