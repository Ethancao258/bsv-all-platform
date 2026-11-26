# URA｜Universal Reference Architecture 全平台永久引用架构 V1.0
状态：DESIGN_READY，非已实现、非已部署。阅读上版 ../cx-parallel-v1-1/README.md、CONTRACT.md、REGISTRY.json 及对应任务书；本版增量补充，冲突以本版设计建议为准，既有 AGENTS.md 与已批准正式契约优先。源码证据基线 2052ef51f011be3c5898d816932d8982f420b752；最新主机状态须由集成人复核。所有路径/表/字段为拟议映射，不是已创建对象。

## 决策
外部依赖可替换，内部事实可追溯，业务政策可统一调整。采用依赖倒置 + 适配器 + 外部配置 + 版本化规则 + 有条件故障转移。不要将所有代码变成动态脚本或任意HTTP调用；纯算法、协议契约、合规硬限制、授权与事务不变量留在代码。参考 Microsoft external config / circuit breaker、AWS outbox。无需购买其云产品。
## 引用分类
|类型|稳定引用示例|权威位置/管理|切换方式|
|---|---|---|---|
|CAPABILITY|cap.payment.collect / cap.coupon.verify|既有change-routing扩展|路由至已审核适配器|
|OPERATION|cx.payment.create.v1|契约注册表|兼容版本或新版本|
|SOURCE|identity.A / supply.A / cx.catalog.read|既有数据源注册|仅已验只读备用；权威写源另行迁移|
|POLICY|policy.commission / policy.membership / policy.benefit / policy.refund / policy.timer / policy.recommendation / policy.booking / policy.payout / policy.age|业务域owner+统一政策目录|按范围、有效期、版本审批|
|RESOURCE|res.menu.public / res.media.product / res.store.layout / res.document.template|资源注册表、受控对象存储|版本/哈希/权限|
|FEATURE|feature.cx.coupon / feature.cx.prepaid|租户/门店/角色开关|关闭新入口，不破坏历史履约|
|ADAPTER|adapter.wechat.pay.v3 / adapter.alipay.wap.v1 / adapter.sqb.coupon.v1|代码注册+依赖锁|测试后启用或替代|
示例ID是候选，集成人与既有编号核对后冻结；保留原12个cx引用作为兼容别名，不改现有稳定实体ID。
## 引用解析（算法）
输入可信 tenant/legal_entity/store/environment、operation、actor scope、channel/context、时刻。先鉴权与功能开关→找到唯一适用reference definition→按具体范围优先、有效期、审批状态查活动binding→筛选能力/合规/授权/入口/健康→选择候选并返回adapter/provider/config_revision或policy_revision。冲突/循环/缺权威来源拒绝；不将任意用户URL、SQL、脚本注入。配置优先规则：系统合规底线不可覆盖，租户默认→合法主体→门店→受审核的更具体范围；同优先级重叠拒绝。租户数据库路由先由受控引导配置解析，避免依赖自己。
政策版本不可原地编辑：草案、校验、试算、审批、生效、退役；版本具生效时刻与范围，历史交易固化policy_id/revision和必要参数快照，退款沿原版本，不重新解释旧合同；新操作读取活动指针。授权、支付、核销、余额必须读可信权威；公共菜单可读审核过且限龄的快照。进程本地缓存只用于无敏感数据/已批准配置，按revision和租户分隔，变更原子生效；关键变更无法确认时fail closed。
## 供应商可用性与安全切换矩阵
读类（地图/商品公开资料）可用已批准备用，标注过期状态；认证发送类（短信）先按同一challenge及额度处理，备用不得绕过验证；身份鉴权/财务余额/实时库存只读权威，不以陈旧副本授权；不可逆外部写入（支付、退款、转账、核销）未发送或证明终态未成功才可换通道；已发送/UNKNOWN锁住原provider/merchant/request_id，查原结果、必要时安全取消，禁止盲重发；正式写库故障不可自动切换独立库。用户支付方式改变须用户确认并适配浏览器环境。
熔断器按tenant+provider+operation统计技术失败/超时，不把业务拒绝或用户取消当故障；closed/open/half-open；阈值/窗口/冷却/超时按实际监控配置、合成测试初值不等于生产SLA。读取有限重试退避，写入只同幂等键/原供应商且协议支持，重试预算集中，防级联。独立fallback能力需真实授权，不能凭配置自动创造备用服务。
## 管理界面与控制
总部配置页按企业/能力显示当前及备选供应商、健康、支持操作/入口、最近验证、授权到期、版本、变更申请/试算/批准/回滚；实际密钥只保存在受控秘密存储，页面仅显示引用及掩码。配置URL仅允许受控白名单、HTTPS、限定路径、禁止随意重定向/DNS重绑定/私网SSRF；内部私有路由单独允许。日志无凭据/个人数据/券码；记录引用版本与相关ID。配置变更不重启业务程序的目标需验证，协议适配器更新仍需正常部署。
## 退出与自研替代
每个关键capability定义数据归属/导出格式、服务商合同/授权、替换成本、可运行备用、人工SOP、历史查询/退款保留、演练日期。供应商退出时停新请求→对账未决→数据导出与核对→切换新绑定→小流量验证→撤旧权限（保留依法需要的历史处理）。自研只替代适配器能力；持牌支付、身份核验等有法定资质的业务不能无资质自营。
## 最短落地
先复用 config/change-routing、现有 identity/supply/pos resolver，A编写兼容入口和版本指针；C/G/H等只使用引用契约；配置存储先用受保护文件/已有数据库，不另购平台，不为每个参数设独立表。旧模块按 LEGACY-AUDIT.md 逐项迁移，不一次性改全系统。系统每次新增功能必须登记owner/ref/type/contract/配置/回退/测试；此文件是未来跨项目架构候选永久规范，待负责人批准纳入现有工程控制面。
