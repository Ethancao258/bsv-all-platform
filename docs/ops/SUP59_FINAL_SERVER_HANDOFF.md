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
