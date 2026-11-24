# BSV ALL 数据访问与导入准备（V2.0 冻结基准）

状态：`APPLICATION_CONTRACT_READY_SCHEMA_PENDING`。本文件是对当前代码的实现盘点；设计字段不等于线上数据库已连接。

## 已审计的事实与兼容边界

| 模块 | 当前实际数据访问 | 当前所有者/兼容配置 | 本次处理 |
|---|---|---|---|
| POS 与调酒 | `services/api/bsv1/app.py` 通过 `bsv_database_config.get_database_path()` 访问既有 SQLite；订单、座位、员工会话、目录投影均仍由现有 POS API/SQLite 管理。V9 Excel 经 `bsv_v9_import.py` 写入只读目录投影，`bsv_collab.recipe()` 按固定商品/物料 ID 查询制作信息。 | `BSV_DB_PATH`；目录 `BSV_CATALOG_DIR`；`BSV_V9_XLSX`。不连接集团 PG。 | 保持当前写入权威；新增 `/api/v1/catalog/products...` 只读契约映射到既有 API/SQLite；媒体先读持久根目录并保留旧发布素材只读回退。 |
| 身份与学院 | `services/api/identity/database.py` 的 `SourceRouter` 用 SQLAlchemy；学院 API/模型和身份共享身份 A 的授权/人员数据服务，不建立另一个学院人员库。 | `config/modules/identity-data-sources.json` 中 A 主变量=`BSV_DB_URL`，隔离兼容别名=`BSV_DB_A_URL`，B=`BSV_DB_B_READONLY_URL`，LOCAL 仅加密归档。隔离测试默认库不代表生产。 | 保留旧 A/B/LOCAL 别名；中心变量只有在明确提供时才被服务读取。尚未改生产/隔离环境 URL，也未执行 DDL。 |
| 供货、库存、督查 | `services/api/supply/config.py` 读取 A–G HTTP 数据源配置；`cache.py` 和 `demo.py` 使用本地 SQLite 缓存/演示事实。A–G 是服务/连接别名，不是七套主库。 | `BSV_SOURCES_CONFIG`、`BSV_MODE`、`BSV_SUPPLY_STATE_DIR`；配置仍遵守 A–G 原映射。 | 继续复用现有服务 API，不切换或误认作 PG 连接串；本轮没有把本地缓存改成权威写入。 |
| 会员增长 | `services/api/customer_growth/app.py` 使用 SQLAlchemy，运行库由 `BSV_GROWTH_DB_URL` 配置；隔离模式可用 SQLite。 | `BSV_GROWTH_DB_URL` 及现有身份服务链接。 | 保留兼容变量；等待 WorkBuddy 字段字典及真实迁移审批后再改适配层。未把 SQLite 测试库升级成正式主库。 |
| 电子菜单 | EdgeOne/Git 中的 `apps/guest-web` 静态公开快照由 `public_menu_projection.py` 从批准的安全投影生成；POS 菜单预览走 POS API。 | `contracts/menu/public-menu-v2.schema.json` 与当前公开投影契约。 | 不连接私有数据库、不读成本或员工信息；保留静态公开快照边界。 |
| PostgreSQL/CloudBase | `contracts/database/field-dictionary.json` 对 CloudBase 标记 `UNKNOWN_G0`；本地 PG17 身份预检由隔离迁移测试管理。 | 正式目标名统一登记为 `bsv_all_prod`。 | 此 PR 只提供 DSN/数据访问契约；不建库、不运行迁移、不导入正式数据。 |

## 统一入口

`config/data-contracts.json` 引用而不复制 `config/data-ownership.json`、模块 A/B/LOCAL 配置和既有 POS 领域契约。永久主键所有权继续由原注册表决定。`BSV_DB_URL` 是未来正式 PostgreSQL 连接变量，必须指向 `bsv_all_prod`；当前不配置密钥、不自动连接。identity/supply/growth/POS 兼容变量在各域迁移验收前保留。

目录 API 返回 `contract_version` 和稳定语义键（例如 `product_id`、`recipe_steps`、`sourcing_guide`）；源 Excel 表头到语义键的映射只存在于统一注册表。当前本地 SQLite/Excel 是该映射的适配实现，未声明 PostgreSQL 物理表/列。

## 产品图片与更新边界

持久图片根目录：`BSV_PRODUCT_MEDIA_ROOT`，默认 `/var/lib/bsv-all/media/products/{product_id}/{原文件名}`。POS 响应仅在已登录员工接口内读取，并校验永久商品 ID、文件名扩展名、路径包含关系及软链接。旧 release 的图片路径只作兼容读取，禁止把新上传继续写入程序发布目录。

目录版本仍独立于程序 SHA。新导入命令阶段为 `archive → preview → validate → commit-candidate → publish`；只有最后一步调用现有 V9 解析/SQLite 同步事务，保留原版本和 rollback。现有 `stage` 命令保留以兼容已经部署的运维流程。未来 CloudBase 对象下载器必须先核验私有对象身份、对象路径和 SHA，再调用同一验证/导入入口；此 PR 不创建定时任务或云端凭据。

## Schema 与发布规则

- 程序版本：Git commit SHA；内容版本：工作簿 SHA256/独立活动指针；数据库结构版本：只允许 `cloudbase/migrations/` 官方账本。
- 适配本地 SQLite 时只读映射；PG 适配器只能在字段字典审查完成后实现。
- 迁移前必须由 WorkBuddy 提供并审查字段字典，之后核实真实 CloudBase schema、所有权/迁移记录、权限、备份与恢复证据；同一实体只有一个被批准写入源。
- 禁止把 POS SQLite、身份隔离测试库、供货离线缓存升级为集团正式权威主库；禁止无双向证据的双写。

## 隔离部署所需变量（候选，不代表主机已修改）

```ini
BSV_DB_URL=postgresql+psycopg://<service-user>:<secret>@<verified-host>/bsv_all_prod
BSV_PRODUCT_MEDIA_ROOT=/var/lib/bsv-all/media/products
```

密钥应放在 `/etc/bsv-all/database.env` 等受限配置中，不进入 Git。先经批准的备份、账号权限与目标库核验；本 PR 未生成表或变更任何正在运行服务。
