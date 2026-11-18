# Codex 集成归档地图（不添加第 15 个一级目录）

主仓库：`Ethancao258/bsv-all-platform`，冻结根目录：`.github`、`apps`、`capabilities`、`domains`、`services`、`integrations`、`cloudbase`、`contracts`、`platform`、`ingestion`、`docs`、`config`、`tests`、`scripts`。**以下是推荐的最小冲突分拆映射，不可对现有同名文件无脑覆盖；整合前先看差异和 PR 堆栈。**

| 本包实际文件 | 目标主仓位置（建议） | 冲突规则 |
|---|---|---|
| `bsv_identity/web/staff.html` + `web/static/staff.js` | `apps/staff-center/identity/` | 使用 BSV ALL 既有网页壳/域名路由；不要覆盖学习中心 |
| `bsv_identity/web/hq.html` + `web/static/hq.js` | `apps/hq-console/identity/` | 只加人员管理模块；不得重新定义总部权限字典 |
| `bsv_identity/web/static/common.js`/`style.css` | `apps/staff-center/identity/assets/`，共享组件由 Codex 统一抽取 | 避免覆盖现有样式文件 |
| `bsv_identity/api.py`、`config.py`、`database.py` | `services/api/identity/` | 将 API Router 挂到既有 FastAPI 进程；不要运行第二个生产 API 主服务/认证中心；先排查现有路由冲突 |
| `bsv_identity/core.py` 中 TR allocator/人员/任职逻辑 | `domains/workforce/identity/` | TR 权威业务码；既有 `employee_id` 是兼容投影/映射，不得按 EMP 再发号码 |
| `bsv_identity/core.py` 中会话/授权/BM/roles + `security.py` | `domains/identity_access/` 与受控适配器 `integrations/auth/` | 认证凭据继续由既有 CloudBase Auth 持有；本包测试认证账号不能生产迁移 |
| `bsv_identity/models.py` | `domains/workforce/identity/` 与 `domains/identity_access/` 候选实体 | Codex 需检查已有表、归属和 1:N 关系；候选 15 表**不允许原样盲建入生产** |
| `Qualification` 外键和接口 | `domains/learning/` 仅建立对已有资格服务的引用契约 | 不复制题库、课程、成绩和凭证签发权 |
| `bsv_identity/backup.py`、`config/data_sources.json` | `platform/lighthouse/identity/` + `config/identity-data-sources.json` | 优先复用主仓已有共享 DB 注册表，禁止并列多个主 DB 来源；A/B 是逻辑命名 |
| `contracts/identity.openapi.json`、候选 DDL | `contracts/identity/` | 接口要与 POS/供货/原认证统一版本管理 |
| `migrations/versions/...` | **不直接拷到 `cloudbase/migrations/`** | 仅作候选参考：通过 G0/G1 真实盘点、备份验证、CloudBase **官方** plan/apply 迁移审批后才创建官方生产迁移文件 |
| `tests/*`、`evidence/*` | `tests/identity/`、`docs/ops/identity-evidence/` | 在合并后的 POS/菜单/供货分支重新跑 CI、跨模块权限测试 |
| `deploy/systemd/`、`Dockerfile`、`deploy/docker-compose.staging.yml` | `platform/lighthouse/identity/` | 查实服务器原有端口与进程/路径，决定复用现有服务或隔离部署；不能开第二套收银系统 |
| `docs/`、`review/`、`README.md`、`CODEX_HANDOFF.md` | `docs/architecture/identity/` 或 `docs/ops/` | 保留本次 UNKNOWN/阻断证据；不能把本次测试记作云端 PASS |
| `deploy/ci-identity.yml` | `.github/workflows/identity-validation.yml` | 先调整路径/依赖并在主仓 CI 实跑；不能与已有工作流冲突 |
| 旧码 `LegacyAlias` / preview | `ingestion/mappings/identity/` | 先映射原门店旧 TR/EMP/BM、POS 订单操作员、供货领用员，迁移预检后审批 |

**现有 `config/data-ownership.json` 已定义** `employee_id: workforce`、`auth_subject_id: identity_access`；不可改变归属，建议增量补充 `tr_code: workforce`、`stage_issuance_id: workforce`、`management_appointment_id: identity_access`、`auth_link_id: identity_access`、`legacy_alias_id: workforce`；参见 `docs/DATA_OWNERSHIP_PATCH.json`，这不是已经在 GitHub 应用的修改。

## 合并之前的 PR / 数据核对

1. `git fetch`，只读确认 `main`、PR #1、#2、#4 的**实时**状态与最终 merge base；本次 Issue #3 记录它们曾经堆叠，**不保证当前仍未合并**。
2. 在完整包含 POS、菜单、供货成果的工作分支创建 `feature/identity-permanent-tr-v2-r2`；先恢复主仓架构锁并运行 `scripts/verify_architecture.py`。
3. 同步检查 `services/api` 的认证、座位/订单操作员、供货领用记录使用哪一个现有员工 ID；通过 `legacy_aliases` 映射，不能批量重发 TR、不能删原始操作员历史。
4. 管理 A 中人与认证服务身份映射，校验数据库唯一性、真实门店/法人 ID 和 learning 凭证；生产 V2.9 POS 不应读一个旁路新数据库。
5. 生产前依照现有 GitHub `AGENTS.md`，对 CloudBase 只读 G0、备份 G1、迁移审批，最后才提带回滚材料的独立 PR，禁止直接推 main 和启用自动生产发布。
