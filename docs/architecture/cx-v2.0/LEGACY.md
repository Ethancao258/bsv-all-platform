# 历史系统URA改造清单
状态：DESIGN_READY，非已实现、非已部署。阅读上版 ../cx-parallel-v1-1/README.md、CONTRACT.md、REGISTRY.json 及对应任务书；本版增量补充，冲突以本版设计建议为准，既有 AGENTS.md 与已批准正式契约优先。源码证据基线 2052ef51f011be3c5898d816932d8982f420b752；最新主机状态须由集成人复核。所有路径/表/字段为拟议映射，不是已创建对象。

证据是GitHub指定历史SHA的源码阅读及用户提供的主机摸排；不代表最新生产状态。优先做与八线直接冲突的缺口，其他以增量补丁收口。原始主机报告不上传。
|编号|证据与发现|处理路径|优先级/owner|
|---|---|---|---|
|URA-L01|services/api/customer_growth/app.py 508–608：微信OAuth官方URL在业务函数中，sms_enabled=False，进程级微信/门店/法人配置|B抽出已实现微信adapter；A统一租户binding，保留OAuth state和现有客户ID|P0 A/B|
|URA-L02|同文件1–110：全局DSN、STORES、LEGAL_ENTITY、签名、会员政策版本；中央数据库名称固定检查；身份绑定尚未包含issuer/tenant语义（508–608）|A/B兼容解析，真实schema核验，先两租户隔离；原合法隔离限制不得无理由放开|P0 A/B|
|URA-L03|同文件1045–1165：会员期限程序常量、固定权益种类、预占时长；过期预占释放未见外部终态检查|D复用模型，引用版本政策，增加未知支付不释放测试，现有真实权益保留|P0 D/H|
|URA-L04|同文件995–1043、1045–1115：按store/effective_at选政策、历史退款保留rate/coeff；PaymentFact按order_id单笔PAID，事件没有独立履约事实|E/H扩展分次付款/退款与事件版本、明确归因和结算时点，原算法回归|P0 E/H|
|URA-L05|services/api/bsv1/bsv_growth_pos.py 1–110：现有签名120秒关联/90秒只读上下文，无完整多租户绑定|F/B保留现有接口，增加租户scope与独立下单授权，不改旧签名语义|P0 F/B+POS owner|
|URA-L06|services/api/bsv1/bsv_catalog_config.py 1–100：Excel版本指针、hash核验和环境变量；bsv_catalog_repository.py 1–95：现有shared resolver但直接读环境DSN、隔离loopback限制|C/A扩展既有版本路由，保留hash/隔离；公开投影与权威可售分离，不重做导入|P1 A/C+POS owner|
|URA-L07|services/api/supply/gateway.py 1–100：按A-G配置、只读备用/缓存、写入失败关闭；当前缓存key包含principal/scope，需多租户与数据分类评估|复用机制，补tenant/revision命名空间及能力/缓存策略；不擅自改供货流程|P1 A+供货owner|
|URA-L08|integrations/auth/identity_client.py 1–90：单一环境URL、门店法人JSON、实时鉴权，不缓存决定|A+身份owner兼容引用，保留实时权限fail-closed，验证跨租户|P1 A+identity owner|
|URA-L09|services/api/bsv1/bsv_database_config.py / bsv_data_router.py / reference_adapter.py：已有环境路径、只读参考快照规则；实际权威写源切换不能自动|保留现有POS SQLite权威边界，统一名称与路由，不复制或强迁数据库|P1 A+POS owner|
|URA-L10|用户报告 integrations/payment/marketplaces主要是占位；真实结账demo；存酒/计时最后检索未完成|G/H独立适配，D只授权核验现有实现；不得绕过工具拒绝|P0 G/H/D|
|URA-L11|员工薪酬/学院/排班/合同/打印/督查的其他政策引用和供应商配置未完成源码审计|各现有owner按URA检查，不判定缺陷；先静态扫描候选，再逐项真实证据与最小修改|P2 PM协调|
## 改造验收
第一波 L01–L05/L10 嵌入现有八线，不另开重构项目；第二波L06–L09须原owner批准与旧接口回归；L11待授权逐模块审计。扫描候选：业务层URL/DSN/供应商SDK、硬编码经营参数、默认店/法人、跨域直读、重复政策、无版本历史、缓存键/回调/文件路径未含租户；排除测试常量、协议固定端点（adapter内部）、安全不变量、合法默认值。输出文件:行、实际影响、替换ref、旧兼容方式、迁移候选、正反回归与证据。不是全局搜索替换URL，更不是全面重写。


V2只按实际缺口随业务增量改造；最新生产状态未核实，不做全局重写。