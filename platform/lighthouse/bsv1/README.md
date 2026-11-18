# BSV1 Lighthouse 私有验收准备

目标为 Ubuntu 24.04 的 Python 3.12 标准库，前端为随程序分发的静态文件。运行时无需 pip/npm 下载，CI 使用 Python 3.12 与 Node.js 22 校验源码。应用仅绑定 loopback。

## 预检与可复现启动

- `bash platform/lighthouse/bsv1/release.sh --simulate` 在临时目录验证版本切换、HTTP 健康、失败回切及启动；可在仓库 checkout 中运行。
- 获得授权后，在目标机运行 `bash platform/lighthouse/bsv1/release.sh --dry-run`。核实实际 V2.9 服务、源码和 SQLite 路径、代理与监听、可用磁盘、权限及恢复条件。现用地址及路径来自交接包，仍待远端实测。
- 用经 CI 的 Git SHA 准备独立版本目录 `/opt/bsv-all-bsv1-stage/releases/<SHA>/`，保留仓库相对运行布局 `apps/` 与 `services/`。建立专用无登录用户 `bsv-all-stage`，使用权限受控的独立 `/var/lib/bsv-all-bsv1-stage`，按模板生成 0600 环境文件。在隔离目录放入已批准的 V9 工作簿并校验 SHA。
- 由运维在受控会话加载环境模板键值，以专用账号用 `manage_staff.py add` 交互创建独立验收账号，有需要再通过 `hq_grant.py` 显式授权。以 root 管理的原子符号链接切换 `current`，加载独立 systemd 单元，启动前保存旧链接和备份。通过专用 SSH 隧道验收，保持 V2.9 的监听和目录。
- 使用 `python3 platform/lighthouse/bsv1/health.py 8767` 与 `journalctl -u bsv-all-bsv1-stage.service` 核验。失败时停止独立服务、保存日志，并原子回切到上一个已验收版本后重启；首次安装失败时保留停用。数据库版本不兼容时先恢复到新的隔离路径并核验，不能仅切代码后继续写。

## 数据边界

SQLite 仅存隔离验收数据。用相同环境执行 `services/api/bsv1/backup_db.py` 生成一致性备份，恢复到另一文件后跑完整性、外键及业务计数校验。上线前另验加密异地副本和实际 RPO/RTO。CloudBase 按注册表和正式迁移门槛接入；当前 DB_A/DB_B 仅有读取接口和决策测试，线上切换、写入、真实支付均未启用。
