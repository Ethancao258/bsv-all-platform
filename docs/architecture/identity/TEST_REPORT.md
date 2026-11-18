# 真实执行证据与范围说明｜2026-11-18（隔离）

| 验证 | 结果 | 证据或限制 |
|---|---|---|
| 39 条 pytest 测试（核心、HTTP、权限、备份、对抗） | **PASS** | `evidence/pytest-final.txt`，运行时由 SQLite 隔离库支持 |
| 100 个不同并发申请/审批的原子码分配 | **PASS(SQLite 模拟事务)** | `tests/test_core.py::test_100_concurrent_distinct_registration_and_code_allocations`；非 PostgreSQL 锁压力测试 |
| 同一幂等键大量重复请求、同名不自动合并、容量末尾 | **PASS** | `tests/test_core.py` 和 `tests/test_hardening.py` |
| TR→EMP→BM/双人批准、门店/跨法人隔离、即时撤权 | **PASS** | `tests/test_api.py`, `test_hardening.py` |
| AES-256-GCM 加密备份/受控还原、密钥权限拒绝 | **PASS(SQLite)** | `tests/test_backup.py` |
| Alembic 独立 SQLite 迁移 | **PASS** | `evidence/alembic-smoke.txt`；绝非 CloudBase 迁移验证 |
| PostgreSQL 17 候选 SQLAlchemy DDL | **生成成功/静态模拟编译** | `contracts/candidate-postgresql17-schema.sql`，不等同于真实 PG17 执行 |
| HTTP 服务端在线检查、双网页、公开配置与 OpenAPI | **HTTP 200** | `evidence/http-smoke.txt`，在 `127.0.0.1:18766` 隔离服务真实执行 |
| 独立 Uvicorn 进程运行端到端测试（申请/幂等/双人核验/批准） | **PASS** | `evidence/http-live-e2e.json`：TRA0003、拒绝普通用户访问 HQ 403 |
| JS 静态语法 | **PASS** | `node --check` 3 份脚本 |
| 本地部署计划预检 | **PASS_LOCAL_PREFLIGHT** | `evidence/deploy-preflight.json` |
| Chromium 截图 | **UNKNOWN** | 当前无可用 headless 图形截图证据，命令超时，不能冒充浏览器视觉验收 |
| Docker 镜像构建、Compose 启动、真实 PG17 事务锁 | **NOT RUN** | 当前执行容器无 Docker / PG17 服务器，且 psycopg 安装不可通过网络完成 |
| 真实 CloudBase/Lighthouse/EdgeOne/生产 JWT/HTTPS | **NOT RUN** | 没有授权，禁止对线上服务修改 |
| GitHub PR CI、14 根目录整合后验证 | **NOT RUN** | 未推送仓库；已有 14 根目录配置已通过只读查询核验 |

## 发现及修正记录

- R1 测试最初失败：注册接口 `201` 状态不符、SQL 外键负例未回滚；修复后重新运行 20 项测试通过。
- R2 挑错增加多段任职结束、独立 POS/供货资格、跨法人查询及跨法人全局停用/恢复/脱敏锁定、遗失账号双人恢复、隐私双人脱敏、同步撤权、同幂等键并发与审计读隔离；最终现有 39 条测试通过。
- PostgreSQL DDL 模拟编译曾因 `RAISE` 百分号转义失败，修复为 SQLAlchemy 的 DDL `%` 转义，最终生成候选 SQL 并做静态检验。
- 本报告无假设性“100% 安全”或“真实生产 PG 并发已验证”声明。任何生产数据处理都要另做真实授权和独立复核。
