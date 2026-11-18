# BSV ALL｜Codex 正式移交与上线门槛

## 一句话交付

**完整隔离代码 R2**：Python FastAPI + SQLAlchemy + web UI + 候选 PostgreSQL schema + 事务 TR→EMP→BM + 认证/授权 + 加密备份 + 合成数据 + 自动化测试；目标主仓 `Ethancao258/bsv-all-platform`，不改变 14 个一级目录，不创建第二公司主库。已访问 GitHub **只读**，本轮没有任何 push、PR、生产迁移或云端部署。

## 真实可核验状态（谨防误判）

- `VERIFIED_LOCAL`：SQLite 单机 Alembic 迁移、HTTP 200（`/staff`/`/hq`/OpenAPI/健康）、Node JS 语法、39 pytest 测试、PostgreSQL 候选 DDL 静态模拟生成、加密本地 SQLite 备份恢复。
- `NOT VERIFIED`：Docker 正式镜像构建及 Ubuntu24.04 本机运行、真正 PostgreSQL 17 迁移/并发、真实 CloudBase Auth、CloudBase RLS/GRANT 与主库 10 表、Lighthouse 端口/TLS/systemd、真实员工实名去重、学习资格签发方、生产部门权限、异地恢复演练、浏览器视觉真机。
- `PROHIBITED UNTIL G0/G1`：任何 CloudBase 生产 DDL/DML、直接导入测试账号表、向旧 POS 系统覆盖数据库、自动修改 BSV ALL 的 `config/data-ownership.json`、多主数据写入。

## 整合操作顺序（逐门槛推进）

**G0** 只读盘点已有 CloudBase schema、列索引/约束、主库归属、既有门店/员工/资格/认证对象、官方迁移历史、GRANT/RLS；记录证据与时间。

**G1** 对真实主库现有备份的合法性、密钥、保留、恢复目标和在隔离库的恢复演练做证据核验；无有效恢复计划则 **NO-GO**。

**G2** 在不更改根目录下，把本包文件按 `INTEGRATION_MAP.md` 进行有差异的最小归位；复用现有 CloudBase Auth，禁用隔离认证；检查 API 路由和 `employee_id` 与 TR 的权威映射；高权限身份恢复/撤权最小可用闭环重测。

**G3** 在真正 PG17 隔离 staging 执行候选迁移并实测 100 并发发码、同人多请求、唯一约束/触发器/撤权、PG 客户端加密快照与恢复、跨店/跨法人的拒绝；不可由 SQLite 测试代替。

**G4** 重新梳理新旧 employee_id/历史单据/培训/授权 API 的契约；与含 PR #1/#2/#4 的基线进行合并，跑全主仓 CI；经审查后创建独立 PR，不能推生产 main。

**G5** Lighthouse 只读核实已有 API、端口、进程、工作目录、证书/反代和访问控制；在**隔离且受保护的 staging 路径**正式构建/恢复演练；人工审批后才能发布。生产必须使用正式外部 Auth、可信服务身份、TLS、网关限流、严格数据访问角色、审计与监控。

## 快速验收（隔离工程）

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export BSV_APP_ENV=isolated BSV_AUTH_PROVIDER=isolated
export BSV_DB_A_URL="sqlite+pysqlite:///./runtime/identity-isolated.db"
export BSV_DEMO_ADMIN_1_PASSWORD='CHANGE_TO_SYNTHETIC_TEST_ONLY_PASSWORD_A'
export BSV_DEMO_ADMIN_2_PASSWORD='CHANGE_TO_SYNTHETIC_TEST_ONLY_PASSWORD_B'
python -m alembic upgrade head
python -m bsv_identity.seed_isolated --i-understand-isolated
python scripts/deploy_dry_run.py --dry-run
python -m pytest -ra
uvicorn bsv_identity.api:app --host 127.0.0.1 --port 18765
# second terminal: curl -f http://127.0.0.1:18765/health/ready
```

## 数据所有权与 ID 约束

`tr_code` 唯一归 `workforce`；`employee_id` 如果既有员工实体/字段则以明确兼容别名、投影视图或映射指向 TR，绝不再按独立 EMP 号码池发号。`auth_subject_id` 归 `identity_access`，`learning_credential_id` 只引用学习系统，`store_id`/`legal_entity_id` 只引用组织域。`EMPA0001`、`BMA0001` 既不是新自然人 ID 也不是密码。

## 最终向经营负责人汇报必须包含

是否部署（默认 NO），当前 Git SHA（本包没有 Git 提交 SHA，应在未来 PR 提交后才写）、现存资源真实 ID（未授权则 UNKNOWN）、官方 CloudBase 迁移版本、CI 结果、PG17 真实并发和回滚验证、旧码冲突数量、生产数据涉及的个人信息处理合法性、不可完成项与下一关口。不能因为“程序可运行”就汇报“已在服务器正式运行”。
