# BSV ALL｜统一人员身份与 TR→EMP→BM 权限系统 V2.0（R2）

> **结论：隔离版可运行；正式云端上线尚未获准，也未经真实 PostgreSQL 17/CloudBase/Lighthouse 的运行验收。** 这是完整 FastAPI/SQLAlchemy/网页项目，不是页面原型。CloudBase 既有数据库不被本包修改。

## 1. 固定不可变业务规则

- 每个真实自然人仅一个终身 TR 主码：`TRA0001`。同一人 EMP=`EMPA0001`，BM=`BMA0001`，**同一五位后缀**；EMP/BM **不消耗新编号**。
- 字母 `ABCDEFGHJKLMNPQRSTUVWXYZ`（不含 I/O），每字母 `0001`—`9999`，容量 **239,976**。`TRA9999`→`TRB0001`。永不重用发过的号码；删除隐私资料仅保留码占用墓碑。
- 永久阶段颁发历史、有效任职、资格引用、BM 任命、法人、门店、角色及具体操作权限相互独立；**猜到任一码不得获取权限**。
- TR→EMP 需要独立批准的任职和入门资格；TR→EMP→BM 需要当前任职、管理资格、独立任命审批；离职/转店/撤权不会产生新 TR/EMP/BM。
- **只有数据库 A 是权限、发码、审批、审计的权威读写来源。数据库 B 仅作可选、物理只读的参考源。LOCAL 是加密灾备，不参与实时授权。A 不可用则拒绝权限。** 统一更换来源只修改 `config/data_sources.json` 中 A/B 环境变量名及 `.env` 的 URL，不修改业务代码。

## 2. 项目内容

| 位置 | 可执行内容 |
|---|---|
| `bsv_identity/core.py` | 事务发号、阶段审批、双人分权、实际任职、BM、资格、授权、撤权、回收/复职、旧码预检与隐私审批 |
| `bsv_identity/models.py` | **15 张候选业务表**、唯一约束、外键、索引、PostgreSQL 永久 TR/审计触发器 |
| `bsv_identity/api.py` | FastAPI **40 条 OpenAPI 路径**；本人/总部/跨服务接口、健康检查 |
| `bsv_identity/web/` | 简体中文手机端与总部桌面端网页、真实 API 操作表单 |
| `bsv_identity/security.py` | 隔离演练 Argon2 账号；正式 CloudBase JWKS 候选适配、可撤销服务端会话、CSRF |
| `config/data_sources.json` | A/B/LOCAL 单点路由配置 |
| `bsv_identity/backup.py` | AES-256-GCM 加密快照、PG `pg_dump` 流、校验、隔离恢复、保留清理 |
| `migrations/` | **仅隔离/模拟** Alembic 迁移，禁止直连现有 CloudBase |
| `contracts/` | OpenAPI 和候选 PostgreSQL 17 DDL；不得直接执行到生产 |
| `tests/` | 真实自动化并发/授权/端到端/迁移/备份/异常测试 |
| `deploy/` | Docker、隔离 PostgreSQL 17 Compose、Ubuntu 24.04 systemd 与每日备份计时器模板 |
| `docs/`、`review/` | 安全与集成边界、两轮三组模拟专家审查、测试证据 |

## 3. 五分钟运行（不连接任何云）

要求：Python **3.11 或 3.12**、pip、独立测试目录。请使用**虚构测试用户**，不能填真实员工、手机号、身份证或合同。

```bash
cd BSV_ALL_TR_identity_V2.0
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
mkdir -p runtime
export BSV_APP_ENV=isolated
export BSV_AUTH_PROVIDER=isolated
export BSV_DB_A_URL="sqlite+pysqlite:///./runtime/identity-isolated.db"
export BSV_DEMO_ADMIN_1_PASSWORD='CHANGE-THIS-A-STRONG-SYNTHETIC-TEST-PASSWORD'
export BSV_DEMO_ADMIN_2_PASSWORD='CHANGE-THIS-B-STRONG-SYNTHETIC-TEST-PASSWORD'
python -m alembic upgrade head
python -m bsv_identity.seed_isolated --i-understand-isolated
python scripts/verify_static.py
python -m pytest -ra
uvicorn bsv_identity.api:app --host 127.0.0.1 --port 18765
```

浏览器：`http://127.0.0.1:18765/staff` 本人页；`/hq` 总部页；`/api/docs` Swagger；`/health/live` 与 `/health/ready`；创建的 `reviewer1`/`reviewer2` 使用上述隔离演练密码进行双人审批。**演练种子管理员与密码哈希不允许进入生产数据库或 Git。**

可替代 SQLite 的 PostgreSQL 17 隔离部署见 [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)。无法取得 Docker/PG 运行环境时不得声明 PostgreSQL 已通过实机验收。

## 4. 开发流程

```bash
python scripts/deploy_dry_run.py --dry-run
python scripts/export_contracts.py
python -m pytest -ra
python -m bsv_identity.cli check-ready
```

- **DB A 当前指向测试实例**：SQLite 仅供本地单机验收；切换到隔离 PostgreSQL 17 的 URL，不改发号逻辑。
- **DB B** 默认不开启：配置只读副本 URL 可增加非敏感参考查询能力，**不能做数据库 A 自动故障切换/写入/权限回退**。
- **LOCAL**：配置与定期加密快照操作详见 [`docs/DB_A_B_AND_BACKUP.md`](docs/DB_A_B_AND_BACKUP.md)。
- 不提交 `runtime/`、`.env`、员工实名信息、备份/密钥。保留源码与脱敏证据即可。

## 5. 正式上线门槛（当前 NO-GO）

真实 CloudBase PostgreSQL 版本、表、RLS/GRANT、迁移历史及备份 G0/G1 均未知；Lighthouse 上部署、代理/端口/TLS 未盘点；CloudBase JWKS issuer/audience、法人的组织主数据、学习系统真实 qualification_id、旧 POS/供货员工字段映射、隐私告知和人工审核流程仍需 Codex/负责人分别核验。隔离认证只适用于**演练**。见 [`CODEX_HANDOFF.md`](CODEX_HANDOFF.md) 和 [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md)。

**GitHub 源码目标**：`Ethancao258/bsv-all-platform`；本交付未推送任何仓库文件，14 个一级目录无需修改。
