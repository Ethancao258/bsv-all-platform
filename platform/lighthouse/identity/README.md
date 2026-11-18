# Lighthouse 私有身份 staging

选择 Python 3.12 锁定依赖及 systemd。候选发布目录为 /srv/bsv/services/identity/releases/<SHA>，运行版本通过 current 指针，私有状态在 /srv/bsv/data/identity-staging。专用系统用户只可写私有状态。环境文件模式 0600，密钥由受控配置注入。Nginx 模板供审核，云端 TLS 和路由尚未验证。POS 试点须由私有同源网关传递集团会话，旧 HQ 不得被覆盖。

从仓库根目录安装 services/api/identity/requirements.lock，再运行 bash tests/identity/check.sh 和 bash tests/identity/pg/check.sh。后者使用本机 Docker 的一次性回环 PG17、匹配客户端和独立恢复库。launch.sh --dry-run 核对模式、DSN 和端口占用。实际启用前需盘点 V2.9、运行目录、代理和端口。身份服务不应公网直连。

仅在隔离库使用 platform/lighthouse/identity/alembic.ini 运行 Alembic。启动后依据 /health/ready 验收，服务日志使用 journalctl -u bsv-identity，审计和备份密钥单独存储。A 是授权唯一权威；B 使用受限只读账号。发布前保留旧 SHA、路由、迁移版本和加密校验。失败时停用新服务，在隔离库验证恢复后回切旧发布。禁止用沙箱 Alembic 回退生产库。
