# BSV ALL Supply V2 兼容契约

原始技术交接见 `HANDOFF.md`；其中旧目录、端口、权限缓存和示例身份规则由本集成契约更新。`openapi.json` 由当前 FastAPI 实现生成。SQL 是历史设计候选，不构成正式迁移。

| 接口槽位 | 权威边界 |
|---|---|
| A | 集团 catalog 的产品、物料与批准清单。复用集团 DB-A，菜单公开快照 DB-A-PUBLIC 仅供展示 |
| B | identity_access 校验公司令牌，workforce/organization 提供员工与业务范围。每次请求重新核权 |
| C | organization 门店、仓储网点及库位只读 |
| D | production 配送/批次，inventory 库存流水与盘点观察，procurement 采购事实；各域唯一写入通过中央认证事务 API |
| E | quality 六项门店自检与独立督查。scope/actor/权限由主服务验证；独立复核和提交人、受检员工分离 |
| F | integrations/vision 候选；默认本地二维码。外部传输受服务器开关与单次授权双重约束 |
| G | event_audit 公司通知与事务 Outbox 消费者。集成预留连接槽位，尚无真实发送器 |

`store_id` 采用 BSVM/BSVS/BSVT/BSVF，T 页记录号不能成为门店主键。A 的旧字段 `item_id` 引用 V9 L 列，C 是集团 `product_id`，M 是 `material_id`；P 预调键保持原值，正式域归属与映射仍待实际表对照，禁止根据 SKU 或名称转换。K 为套餐，不能直接当包装物料。旧 `lot_id` 对应集团 `batch_id` 的候选映射，`movement_id` 对应 `stock_movement_id`，需主库审核。旧 `department_id` 保留为 B 服务外部字段，集团组织关系待核。演示生成的 DEMO 仓、批次、实体与流水永不导入生产。

D/E 写入只在收到中央提交确认后视为入账。读备用和缓存须标记旧数据。待同步缓存以提交员工和其单次授权范围隔离；授权变更后旧队列须人工复核。B 不允许备用或缓存，D/E 仍需独立核权及幂等过账。五档盘点只能记观察。真实调账应走经批准的集团库存调整流程。中央服务中断时保留门店原有合法、自主采购和自制能力。POS 消耗与真实库存对账未联通。

`/hq/supply`、`/store/supply`、`/inspector/supply` 复用一套界面与服务权限。真实公司登录界面、中央 D/E 事务后端、部署地址与通知均待接入。
