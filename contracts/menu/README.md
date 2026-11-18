# BSV1 公开菜单契约

`DB-A` 是集团产品主数据的逻辑名，对应 BSV1 路由契约中的 `DB_A`。`DB-A-PUBLIC` 是已发布的 `bsv.public-menu.v2` 只读投影，当前为随站点发布的 V13.1 快照。集团 `catalog` 仍负责商品、套餐及发布，`organization` 仍负责门店身份。

沿用 V9 L 列固定 ID。C 项对应 `product_id`，K 项在公开 JSON 中以 `product_id` 承载原 `bundle_id`，SKU 仅作展示和搜索。门店来自 V9 T 页，现有四个代码与 POS 门店注册表一致。BSVF 是 craft，V13 的 cocktail 选择器只包含其他三家店。集团公开状态由审批的发布快照表达，旧快照的 `menu_catalogue`、`active`、`selectable` 只表示菜单浏览和意向选择，不能授权 POS 成交。C 项沿用 AJ（POS 按整数分重新核价）；K 项优先区域参考价，其次核心参考价，缺价继续为 null。Q 价和门店可售规则须由成交服务核准。意向清单只传 ID、数量、可选 SKU 及门店。

`services/api/bsv1/public_menu_projection.py` 复用 POS 的 V9 读取器，将 C/K/T 送入经过字段白名单的公开投影。它可在本地生成候选内存对象，由人工比对和审批后另行发布。浏览器禁止接触私有工作簿、数据库或凭据。超时只允许回落到配置明确且同源的已批准公开快照；主源和备用都通过结构校验，禁止重定向。当前备用为空，主源失效会显示重试。公开快照不构成数据库备份。
