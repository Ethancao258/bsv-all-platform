# Supply V2 隔离启动与 Lighthouse 准备

在 Python 3.12 虚拟环境安装 `services/api/supply/requirements.lock`。本地用 `bash tests/supply/check.sh` 运行整套测试与 loopback 健康检查。工作目录为主仓库，FastAPI 程序是 `services.api.supply.main:app`。

部署经授权后再确认 `/srv/bsv/services/` 的版本路径、专用账号、反向代理、端口与 POS 当前占用、环境文件权限和恢复证据。由统一服务配置分配 `BSV_SUPPLY_PORT`，不可占用 V2.9/BSV1 的现有端口。程序仅监听 loopback，Supervisor 须明确指定私有外置 `BSV_SUPPLY_STATE_DIR`、`BSV_MODE` 和审核后的配置。先运行 `bash platform/lighthouse/supply/launch.sh --dry-run`，成功后在私有隔离环境执行同一脚本启动并检查 `/api/health`。0 端口仅用于本地演示。

以获准 Git SHA 保存不可变版本目录和旧指针，保留启动日志及状态快照。失败停止供货进程并按旧已验收版本回切；缓存和待同步命令先隔离备份与比对，禁止重用生产库或回灌演示流水。Fernet API 快照工具与 AES-GCM PG 归档工具分开验收；真实 pg_restore 演练须在独立数据库。演示环境不挂生产反向代理、不接真实身份或视觉服务。未安装系统服务、定时任务或生产迁移。
