# SUP-59 一次性服务器接管说明

状态：研发候选，禁止将此文件当作生产批准。以 PR #61 最新通过测试的 SHA 为准。
唯一执行工单 #52。总集成 #58 与冻结 #44 的授权边界继续有效；C 是共享入口唯一写入负责人。

## 执行顺序（腾讯云：环境接入、部署、实机验收）

1. 保全现有 SUP-59 worktree、配置、日志、演示库和本地 Git bundle。检查 C/M1 发布边界；不得覆盖其工作树或自行修改共享 Nginx。
2. 读取 PR #61 新提交，按差异移植到原供货候选工作树。不得继续演示造数。确认现有 D 库存所有者；从既有权威数据库连接中，使用只读账号执行 `python -m platform.lighthouse.supply.sup59_preflight`。实际使用 `PYTHONPATH=. python platform/lighthouse/supply/sup59_preflight.py`（避免 Python 标准库 platform 冲突）。此脚本仅读元数据，返回不兼容列名，不执行 DDL。真实结构不同则提供去敏表列约束与 owner，禁止另立账本。
3. 复用原 A 目录 repository、B 统一身份、C 组织、D 库存及 E/G。A 使用 central_source_adapter.catalog_router 接入既有目录和批准规则投影；C 使用 organization_router 接入已批准组织投影。API 及参数见 contracts/supply/central-v1.md。私有配置和 SHA 固定文件由各权威 owner 提供，不从演示库生成。B 实时动作及门店授权不得绕过。E/G 继续使用既有接口和 D outbox，禁止伪造通知或打卡事实。
4. D 在原权威服务挂载 central_d_postgres.d_router，使用 central_d_runtime 的现成回调；仅在明确同一 D 所有者、同一库、映射已核验时，可用 `uvicorn services.api.supply.central_d_runtime:create_authority_app --factory --host 127.0.0.1 --port <C分配端口>`。候选 SQL 只适用专用隔离数据库，绝不能直接对真实数据库执行。真实迁移必须保留旧 ID、余额、流水和权限，获 C 与 D owner 批准，先备份并独立恢复验证。不得设置 reviewed/enabled 环境变量代替审核。
5. 保留 `/supply-ui/` 命名空间，接入现有统一工作台和 HTTPS Cookie。供货服务 `BSV_SUPPLY_WEB_ORIGIN=https://admin.bsvm.cn`（仅在确认真实正式域名时），使用原 A-G 配置、现有私有环境文件、固定受管端口与 systemd。禁止全局代理 /assets 或 /api。业务页面不再手工输入 Bearer。C 实际批准后才启用正式入口。
6. 在合成库验证真实浏览器完整闭环：登录、门店权限、补货、实际配方/原料批次、逐瓶分装、打印二维码/A4、发货、部分签收、正常耗用、过期隔离、召回、处置、历史期初凭证。测试环境不得写真实库存。备份恢复、重启持久化及旧模块回归。真实经营批准资料缺项集中一次提出，不要求经营者 SSH 或测试 demo。
7. 正式资料齐全并获得固定 SHA 发布批准后，C 执行正式增量发布及 HTTPS 实机验证；最终只交正式网址、可用门店、SHA、验收记录与实体打印/实际盘点等必要现场事项。仍缺真实 owner、真实 schema 或发布授权时，报告明确阻断，不要继续重复演示，不得宣称上线。

## 期初库存凭证
D owner 可发布私有 SHA 固定文件 `BSV_SUP59_OPENING_FILE`、`BSV_SUP59_OPENING_SHA256`，schema_version=1、approval_reference、legal_entity_id、items。每项 evidence_id、legal_entity_id、store_id、approved=true、not_already_accounted=true、approval_reference、item_id、rule_version、unit、produced_at、observed_at、expires_at、opened、opened_at（若已开封）、package_id UUID、batch_id UUID、amount、remaining、producer_id、quality_accepted。均为真实盘点及历史证明，最近24h实盘，未知资料物理隔离，不补造日期。原 ledger 已记账包装不再导入。同一凭证仅能入账一次，不补造配送或原料耗用流水。总部具该门店 dispatch+receive 权限才能在“历史期初库存”确认。没有批准凭证时为空，不阻止新增正常供货。

## 私有配置
使用原服务配置与既有 secrets，不上传真实投影/凭据到 GitHub。预检读取 BSV_SUP59_ORG_PROJECTION_FILE / SHA256（实际名称按代码）、BSV_SUP59_POLICY_FILE / SHA256、BSV_SUP59_D_DSN。预检成功仅代表元数据列形状，不代表真实 schema 语义或正式上线通过。

## 2026-11-28｜已知中央 PostgreSQL 17 结构的首次建账接续
实机回执确认 bsv_all_prod 已有 catalog/core/audit 等21张表，但该库未列出 supply 或 event_audit；身份库是独立演练数据。不能据此断言全企业没有其他库存账本，C仅需按既有服务登记确认 D 是否已有权威事实。若确认为首次 D，使用同一 PostgreSQL 实例、同一 bsv_all_prod 内的新 supply schema，不建第二主库；事件审计仅在既有全公司事件所有者确认无重复时使用该新 ledger。已补充 `contracts/supply/sup59_first_ledger_production.sql`，它与经测试参考表形一致，额外包含数据库名、专属 NOLOGIN D owner、受限运行角色、首次无冲突及审批引用门禁，原目录表不改、默认不执行。C/D 准备数据库 owner 授权的角色、审查真实授权、备份恢复演练，固定合并SHA后集中审批再执行；若任何表/事件域已存在，停止该脚本并映射既有事实。不把审批引用/开关当作授权凭证。运行角色不得加入目录写角色、数据库管理角色或获得目录/身份数据直读权限。
原料首批入账在既有历史期初库存页面支持 `kind=RAW_LOT`，与分装包装共享唯一凭证校验及事务；除公共字段外需要 item_id（真实M）、recipe_item_id（真实P）、recipe_version、unit、remaining、stock_lot_id、received_at、observed_at、expires_at、opened=false、quality_accepted=true、supplier_lot_ref、expiry_evidence_ref。只接受最近24h真实盘点、原包装效期依据及批准配方投入单位；未知/开封/未验收原料不得作为可用量。禁止以手工 INSERT 绕过。原料库存随库存 API 返回 raw_lots；常规采购到货需由 D 既有入库流程接入，不将一次性期初入口伪装成反复采购。原料日常入库、管理端批准规则录入以及正式事件连接若缺，仍是正式营业阻断。
目录权限：原 PostgresCatalogReadRepository 会先 SET ROLE bsv_catalog_reader，直接以 NOINHERIT 运行登录角色 SELECT 基表失败并不证明角色缺权限；复用此现有 A repository，禁止使用 importer 作为业务读取账号或扩大授权。P 读 catalog.semifinished，M 读 catalog.material，原始行/已审核内容分开；C 商品销售状态不等于 P 生产许可。当前真实资料仍需由 #63/PR64 已有总部商品中心维护、审核并发布；原始 recipe_text、shelf_life 不能自动编造成可执行配方。组织资料由 C 从真实法人、门店和仓库注册核验取得，不能用演练身份行。所有已暴露的数据库及服务凭据由C按既有秘密管理统一轮换，不在日志、命令或GitHub重复输出。

## 2026-11-28｜正常原料采购到货及余料安全边界
D 无既有采购入库流程的候选提供 raw-receive / raw-dispose，使用同一 D 事务、物料主码、门店 receive 权限、已批准配方及基础单位；每条实际采购收货行有全法人唯一 receipt_ref，供应商批号及效期凭证进入审计。仅接收已验收未开封原料，不能无实物输入。正常采购与一次性期初分别记流水。库存显示原料批次和余量，隔离/过期余料可登记实际处置。当前原料批准契约仅证明原包装效期，部分耗用后剩余量置 HOLD；不假设开封后仍可按原包装效期使用。若真实经营需要保存开封余料，须由 A 提供批准的物料开封效期、保存条件及 D 质量放行规则，后续接入现有目录和质量域；在此之前须按批准生产批量选择原包装，避免非必要损耗。不能冒称完整原料开封管理已实现。首建 SQL 增加采购行唯一索引；已经运行旧候选DDL的环境不得重跑首次建账，须由D owner审查增量迁移。仍未授权真实部署。
