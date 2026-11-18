# 数据库 A / B、LOCAL 加密存档与故障逻辑

本项目不存在“数据库 A、B 就是两套集团人员主库”的概念。**A、B 是可变逻辑数据源名称；唯一权威写入永远是 A。**

| 逻辑源 | 唯一配置入口 | 数据职责 | 中断策略 |
|---|---|---|---|
| A | `config/data_sources.json` → `routes.A.primary_url_env` → `.env: BSV_DB_A_URL` | 人员 TR、发码计数器、审批、授权、任职、法律隔离审计 | **禁止授权、发码和撤权**；返回 503；不能自动使用过期副本 |
| B | `routes.B.primary_url_env` → `.env: BSV_DB_B_READONLY_URL` | 可选非敏感只读参考数据，必须是相同主数据来源受控副本 | 可关闭 B；不能提升到写库，不回退授权与审计 |
| LOCAL | `routes.LOCAL.path_env` → `.env: BSV_LOCAL_ARCHIVE_DIR`；`key_file_env`→ `BSV_BACKUP_KEY_FILE` | A 的 AES-256-GCM 本地灾难恢复快照 | 离线数据仅供灾难恢复，不能证明当前权限有效 |

要**换数据库实例或地址**：只改 `.env` 的 `BSV_DB_A_URL`，或把 `config/data_sources.json` 中 env-name 指向另一个环境变量；进程经批准重启/滚动切换。变更前后核对权威对象 `tr_code`、发码计数器、唯一约束、事务审计、数据完整性；禁止未经停写协调的双主写入。数据库 B 的连接账号必须有物理层 SELECT-only 授权并部署在可信私网。

## 密钥与计划归档

```bash
mkdir -p runtime/archives
chmod 700 runtime/archives
python -m bsv_identity.backup generate-key --path ./runtime/backup.key
chmod 600 ./runtime/backup.key
export BSV_BACKUP_KEY_FILE=./runtime/backup.key
export BSV_LOCAL_ARCHIVE_DIR=./runtime/archives
python -m bsv_identity.backup create
python -m bsv_identity.backup list
# 验证密码标签/完整性，无写入
python -m bsv_identity.backup restore --archive ./runtime/archives/identity-A-EXAMPLE.bsvenc
# 只在新建的隔离恢复目标实施，不能覆盖线上
python -m bsv_identity.backup restore --archive ./runtime/archives/identity-A-EXAMPLE.bsvenc --target ./runtime/restore-isolated.db --apply-isolated
python -m bsv_identity.backup prune --keep-days 30 --keep-last 7
```

演示文件名需用 `list` 返回的真实路径替换 `EXAMPLE`，不得复制整段并期待文件存在。PostgreSQL 模式调用 `pg_dump --format=custom` 流式加密；默认 `PGSSLMODE=verify-full`，要求正确服务器证书/主机名，可按授权环境配置 CA。加密镜像通过 GCM tag 校验；**不等同于已完成生产 PG17 恢复演练**。

`deploy/systemd/bsv-identity-backup.timer` 每天 04:00 (+最多600秒扰动)执行一次，保留最近至少 7 份并按天数进行多余文件清理；**本地计算机停机/硬盘损坏会连同本地存档一起丢失**。正式需安排密钥异地托管、异地受控加密副本、恢复点目标 RPO、恢复时间 RTO、失效告警、季度恢复演练和个人信息删除申请对历史备份的管控。当前未部署真实计时器。
