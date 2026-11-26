# CX-WP-C｜菜单与门户
共同研发建议，不是强制步骤；MUST见ARCHITECTURE；局部等效优化可直接采用。初始只读START-HERE、本文件及公共ARCHITECTURE；按需查INDEX，不重复读历史。
## Route and evidence
现有H5菜单与公开投影，保持原URL；按feature flag渲染，规则推荐。
Alternative: 官方微信小程序原生入口 + H5作为独立浏览器备用，仍使用同一后端操作契约；不复制商品、会员、订单库。
美团官方顾客点餐自助核销明确支持品牌微信小程序；当获权接口或支付/登录必须小程序时原生入口可能更短。
Adopt if: 取得小程序主体/域名/支付/验券能力，H5不能合法提供关键功能，且实际扫码→点单/核销流程更短；否则不做双前端。
Sources: https://developer.meituan.com/isv/daocan/ ; https://developer.meituan.com/docs/biz/biz_rms_e8a2bfb2-c855-40ff-8565-ee946a5cae2e
## Concrete execution recommendation
现有catalog发布投影→ETag/version→店别公开菜单。推荐硬过滤店别/可售/预算/酒精限制及明确过敏需求；tag Jaccard=交集/并集，预算匹配可配置；空偏好用编辑排序；分数同分按product_id稳定排序。过敏信息未知不得当安全；最终报价F。

## 最小可交付切片
现有发布→公开白名单→门店/菜单/规格选项→硬过滤推荐→C外壳接各组；未知成分/供应明确。
## 真实复用证据（历史SHA，运行态未知）
services/api/bsv1/bsv_catalog_config.py:18–70 _active_catalog/get_excel_path — reuse candidate; approved publication pointer
services/api/bsv1/bsv_catalog_repository.py:46–271 SQLiteCatalogReadRepository/PostgresCatalogReadRepository — read projection only; no confidential fields
## 所属代码及业务对象
guest-web现有门户/公开投影组件与公共视觉；商品owner仍catalog

PublishedMenuProjection(store_id,publication_id,product_id,display_fields,price_minor,availability_state); Favorite(customer_id,product_id,created_at); 公开门店信息引用organization；推荐权重引用policy.recommendation，不复制商品/价格表。

## 界面与业务动作
首页、菜单、服务、我的四入口；店别配置控制入口；菜单过滤、规格/成分、套餐选项、收藏、导航、推荐结果≤3条起步（可调整）；未登录浏览；不支持功能不显示。


## 界面与验收
页面：C-STORE、C-MENU、C-RECOMMEND。复用三端壳，UI/PAGES与DESIGN按需查；本组24项功能按accountable_owner过滤FEATURE-TRACE，操作按owner查INDEX，必要时与delivery_owner合作；schema使用唯一CONTRACTS文件，不逐个创建HTTP。按合成FIXTURES/CASES测试，真实配置留空，外部授权未取得不假装可用。对真实运行路径不明项先只读核实。
## 可直接复制的启动指令
领取CX-WP-C。从总集成人确认的共同开发基线及独立worktree读取START-HERE、ARCHITECTURE、本任务书。选择现有代码复用、首选、备选或更短等效路径，记录证据；按最小切片实现和测试。只改本组文件；共享文件、迁移及POS由真实owner协调。未获授权标BLOCKED_LIVE，使用合成fixture继续开发；不改运行目录、不未经审批部署。交付SHA、功能ID、测试证据、阻断与回退。局部优化无需反复申请。