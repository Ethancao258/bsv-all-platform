# 服务器与工程的准确关系（决策级约束）

## 四种不同位置

| 平台 | 功能 | 代码版本 | 实际数据/文件 | 禁止误解 |
|---|---|---|---|---|
| GitHub 私有仓库 | 源码、契约、迁移、代码审查 | `main`及PR | 不存生产个人数据/密钥 | 不是数据库或线上服务 |
| CloudBase PostgreSQL 上海 | 当前报告的中央业务主库、账号身份 | Git `cloudbase/migrations/` + 云端迁移历史 | 已有10产品业务表（待只读验收） | 不能未核查就新造 product/store 表 |
| Lighthouse 北京 | 现有 BSV1 运行环境、以后可部署受控 API | `services` 与 `platform/lighthouse` | 运行时日志、缓存及必要私有文件 | 不是通过 CloudBase MCP 就能直接管理OS |
| EdgeOne Makers | 已报告的电子菜单托管及未来公众前台 | `apps/guest-web` 发布快照 | 仅已公开审核的菜单资源 | 不能把员工/成本/库存私有表公开 |
| 门店终端 | 断网制单/出品/状态同步 | `apps/store-console` | 离线快照与Outbox，按店隔离 | 不得成为集团第二主数据 |

**固定对客入口：** `menu.bsvm.cn`，当前已设计 `/cocktail/`、`/craft/`；印刷URL优先保持不变；EdgeOne绑定与实际路由需核验，不能直接把网站从EdgeOne换成Lighthouse。

**Lighthouse业务目录保持原有约定**：`/srv/bsv/{core,stores,public,services,data,incoming,ops}`。这是**运行服务器分类**，不应强行复制成GitHub根目录。每个服务真正的 `systemd`、端口、工作目录、部署版本及状态应在 `docs/ops/CURRENT_STATE.md` 记录；未盘点前一律未知。

**潜在架构冲突：** 组织母版 V5 第7.3节提出“经过验证后逐步向Lighthouse统一承载共享业务数据及API”；前期方案以 CloudBase PostgreSQL 为集团主库。两者属于**物理部署方向待决议**，并非业务架构冲突。当前不得立刻迁移既有10表。未来若迁库，必须经独立 ADR、成本/可用性/备份/恢复/性能对照、完整数据校验、短暂停写或CDC切换证明，始终只有一个权威写入源；不改变域ID和API契约。

**跨地域** CloudBase 上海 ↔ Lighthouse 北京的数据库连接模式、TLS、出口IP及实测延迟均需核验。优先通过可信后端 API 通信；不要在所有前端植入PG连接串。
