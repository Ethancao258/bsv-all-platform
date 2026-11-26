# CX-WP-C V1.4 | 客户门户
This is implementation advice, not a mandatory procedure. Use actual host findings to improve it. No live code or activation.
## Route and evidence
现有H5菜单与公开投影，保持原URL；按feature flag渲染，规则推荐。
Alternative: 官方微信小程序原生入口 + H5作为独立浏览器备用，仍使用同一后端操作契约；不复制商品、会员、订单库。
美团官方顾客点餐自助核销明确支持品牌微信小程序；当获权接口或支付/登录必须小程序时原生入口可能更短。
Adopt if: 取得小程序主体/域名/支付/验券能力，H5不能合法提供关键功能，且实际扫码→点单/核销流程更短；否则不做双前端。
Sources: https://developer.meituan.com/isv/daocan/ ; https://developer.meituan.com/docs/biz/biz_rms_e8a2bfb2-c855-40ff-8565-ee946a5cae2e
## Concrete execution recommendation
现有catalog发布投影→ETag/version→店别公开菜单。推荐硬过滤店别/可售/预算/酒精限制及明确过敏需求；tag Jaccard=交集/并集，预算匹配可配置；空偏好用编辑排序；分数同分按product_id稳定排序。过敏信息未知不得当安全；最终报价F。
## New/revised operations
- cx.catalog.public.v1: store_id:id,publication_id:id?,cursor:s? → published_version:id,products:objs,next_cursor:s?; 仅公开投影，不能作为可售授权
- cx.store.list.v1: profile_id:id? → stores:objs; 营业状态、业态、公开地址
- cx.recommend.rank.v1: store_id:id,budget_minor:i?,taste_tags:ss,alcohol_mode:s → products:objs,reason_codes:ss,policy_version:id; 约束过滤在评分前
- cx.catalog.favorite.v1: product_id:id,desired:b → saved:b; 同一商品收藏幂等
- cx.catalog.availability.v1: store_id:id,product_ids:ids → items:objs,observed_at:t; UNKNOWN不等于可售；F仍重新校验
## Deliverable and tests
Read FEATURE-TRACE filtered by accountable_owner and CRITICAL-CASES. Related-only entries need explicit UI/domain work, not false pass. Preserve old code when equivalent. Actual paths and schema mapping validated on host; missing binding null. Compare alternatives using observed implementation effort and recurring fee, authorization, error recovery and rollback. No claim of global best. 
## V1.3 inherited scope (historical, signatures superseded above)
# CX-WP-C｜菜单与对客门户 V1.3
本文件为建议实施规格，不是代码、已上线接口或真实配置。上版V1.1/1.2历史保留；本版细化优先，现行已批准契约/源码约束优先于设计假定。执行者先对照最新主机基线及既有owner，原表/接口可复用即映射，不另建同义实体。只使用专属worktree和合成测试数据库，不直接改部署目录。局部更优方案不破坏契约可记录后采用；跨组、数据归属、资金语义变更提交ADR，由集成人一次冻结。所有外部账号/密钥/报价/门店映射未核验项保留null，绝不能猜测或写入Git。

## 数据模型（候选映射）
PublishedMenuProjection(store_id,publication_id,product_id,display_fields,price_minor,availability_state); Favorite(customer_id,product_id,created_at); 公开门店信息引用organization；推荐权重引用policy.recommendation，不复制商品/价格表。

## 界面与业务动作
首页、菜单、服务、我的四入口；店别配置控制入口；菜单过滤、规格/成分、套餐选项、收藏、导航、推荐结果≤3条起步（可调整）；未登录浏览；不支持功能不显示。

## 可执行工作顺序
C-01. 保留现有H5路径、菜单公开投影及版本发布；白名单输出，不暴露采购成本、配方和内部备注
C-02. 增加业态模板与门店选择、营业状态、导航链接、图文指南；不重新建设地图或图片服务
C-03. 商品快照ETag/版本，静态内容可读备用；可售状态未知不让购买；F服务端最终报价
C-04. 规则排序：硬过滤→标签匹配与预算适配→历史/真实热度（仅有效数据）；得分权重从政策，缺数据使用编辑精选；保留完整菜单
C-05. 对客门户复用B身份、D资产、E佣金、F/H历史投影；未接通的功能只显示明确状态或不展示

