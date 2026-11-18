# BSV ALL｜集团唯一云端经营工程（锁定基线 V2.0）

**业务母版：** BSV-GOV-ARCH-2026-005 V5.0，2026-11-18。SHA-256: `f08cbe38233dd309f523bc9ac7a794b358f3c9c1efb9744e54f31d90b0f9b5ec`。
**状态：** 已完成工程目录、机器可读注册表和检查脚本；没有把这些空模块宣称为上线系统，也没有修改腾讯云生产资源。

## 一个事实系统，三个经营圈层

- **BSV ALL**：全公司数据字典、唯一身份、API、审计和发布基础，不是第四经营圈层。
- **BSV1**：基础经营与服务交付，保障门店在必要安全边界内独立运营。
- **BSV2**：总部增强、增长、中央供货、独立纠错、外部合作与技术授权。
- **BSV3**：资本治理、融资、投资与长期风险，不能混同日常经营财务。

**GitHub 是代码/迁移/契约的事实源；CloudBase PostgreSQL 是当前报告中的业务主库；Lighthouse 是已有业务运行环境；EdgeOne Makers 承载对客菜单。** 以上具体服务状态仍需由 Codex 通过云端只读工具验收。长远是否将主库从 CloudBase 迁至 Lighthouse，不是创建目录时可以安全决定的事情：必须经过独立 ADR、全量迁移及单写者切换测试。

## 不变的14个根目录

| 目录 | 唯一职责 |
|---|---|
| `.github/` | 非生产自动验证与代码协作 |
| `apps/` | 顾客、门店、员工、总部、督查与合作伙伴的界面入口 |
| `capabilities/` | BSV1/2/3 经营用例与动作，按母版职责分类 |
| `domains/` | 跨圈层复用的唯一数据域及事实所有权 |
| `services/` | API、同步、调度等运行进程（不复制域主数据） |
| `integrations/` | 支付、平台、微信、标签打印等外部适配 |
| `cloudbase/` | 官方规范的 PostgreSQL 版本化迁移目录 |
| `contracts/` | 稳定ID、接口、权限、事件、错误码及发布契约 |
| `platform/` | CloudBase、Lighthouse、EdgeOne 的实际运行配置映射 |
| `ingestion/` | 原始资料接入、溯源、映射、质量检查、暂存与隔离 |
| `docs/` | 组织母版、架构、决策、状态、运营手册 |
| `config/` | 所有AI和程序统一读取的机器可读注册表 |
| `tests/` | 单元/权限/契约/跨店/离线/恢复验收 |
| `scripts/` | 静态架构审计、初始化与只读盘点辅助 |

**扩展方式：** 任何新增领域或业务功能先定位已有一级目录，再新增二、三级模块；新域实体必须在 `config/data-ownership.json` 注册唯一所有者，不得直接创建数据库表。

## 推荐阅读（所有AI必须按此顺序）

1. `AGENTS.md`
2. `docs/governance/BSV-GOV-ARCH-2026-005_V5.0_20261118.md`
3. `config/architecture-lock.json`、`config/*registry.json`、`config/data-ownership.json`
4. `config/use-case-registry.json`、`docs/architecture/SYSTEM_MAP.md`、`contracts/`
5. `docs/ops/CURRENT_STATE.md`（仅可核实状态）
6. `docs/ops/BOOTSTRAP_PROMPT.md`（唯一 Codex 初始化指令）

### 第一条执行命令

`python3 scripts/verify_architecture.py`（纯本地，无外部请求、不会操作云端）。

### 本期不能做的事

不得把样本表结构当作 CloudBase 当前10表的真实形状；不得自动迁移生产数据库、迁移实际资金业务、覆盖旧 BSV1 服务、自动将私密原始素材推到 GitHub，或让各AI维护第二份独立主数据。
