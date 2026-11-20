# Lighthouse 内部集成测试版

仅面向既有北京 Lighthouse 的 SSH 隧道。保留 8765、8767、其 systemd 单元和数据目录。新服务安装于 `/opt/bsv-all-internal-stage/releases/<sha>`，测试状态位于 `/var/lib/bsv-all-internal-stage`。全部监听 `127.0.0.1`。请只在受信任的主机和本机 SSH 客户端使用。未来 HTTPS 私有发布需要另行配置可信主机名、Secure Cookie 和访问门禁。

| 启动顺序 | 端口与入口 | 依赖和数据 |
|---|---|---|
| PostgreSQL 17 | 18764，专用 peer socket 及 SCRAM TCP | 独立实例与数据库 `bsv_identity_isolated_internal`。非超级用户拥有该测试库。仅目标库和测试角色可经 TCP 进入。 |
| 人员身份 R2 | 18761，`services.api.identity.api:app` | 独立锁定 venv。A 使用本机 PG，B 不配置。一次性应用已有候选迁移 `bsv_identity_0001`。隔离认证、双审核人及 AES-GCM 归档。 |
| 门店 POS | 18762，`services/api/bsv1/app.py` | Python 标准库。新 SQLite 与仓库生成的合成 V9。服务端对 R2 逐次鉴权。BSVT 测试别名；下单仅允许未付款模式。 |
| 供货和督查 | 18763，`services.api.supply.main:app` | 另一套锁定 venv。仅接 B 身份源。A/C 目录及 D/E 事实服务当前未接，写入返回 503。 |
| 私有入口 | 18760，`ingress:app` | 同源转发 POS、`/staff`、`/hq`、`/supply-ui/hq/supply`、`/supply-ui/inspector/supply`。`/cocktail/` 提供已有菜单文件。`/craft/` 返回 404。 |

## 执行

前置条件为已批准提交、Ubuntu 24.04、sudo、系统 Python 3.12 的 `python3.12-venv` 软件包及位于 `/usr/lib/postgresql/17/bin` 的 PostgreSQL 17 原生服务器和客户端。Ubuntu 24.04 默认 PostgreSQL 主版本为 16。由主机管理员从已批准的软件源准备 PG17，确认安装不会启动或改动既有数据库服务。部署脚本只检测系统依赖。身份和供货的 pip 均由 venv 提供。无需 Docker。构建需要能读取包索引。

从与批准 SHA 一致的干净 checkout 执行，任一步失败即停止：

```bash
set -e
script=platform/lighthouse/internal-stage/stage.py
python3 "$script" --preflight --sha "$(git rev-parse HEAD)"
sudo python3 "$script" --deploy --sha "$(git rev-parse HEAD)"
python3 "$script" --verify
```

成功应出现 `PREFLIGHT_OK`、`DEPLOYED_INTERNAL_STAGE` 和 `VERIFY_OK`。首次失败会停止新单元并保留测试数据。更新失败会切回上版并复核。手动执行 `sudo python3 "$script" --rollback` 可回切，首个版本则停止新服务。版本回切保留两版源码、PG 数据和 SQLite。迁移目录变化会阻止滚动升级。用 `journalctl -u 'bsv-all-internal-stage@*.service'` 检查新服务日志。

在自己的电脑执行 `ssh -N -L 18760:127.0.0.1:18760 ubuntu@<现有主机>`，打开 `http://127.0.0.1:18760/`。从管理终端私下读取 `/opt/bsv-all-internal-stage/config/` 中属于本测试人员的凭据（`reviewer1`、`reviewer2` 或 `pos-pin`）。审核人员登录 `/hq`，对合成申请走注册、任职、EMP、资格和门店岗位审批。用旧码预检确认 `bsv1_pos,SYNTH-STAGE-POS-01,<合成TR码>` 后再提交映射。POS 先登录 `/staff`，再用 `STAGEPOS01` 和测试 PIN 进入 BSVT（需要二次认证）。供货与督查沿用员工 Cookie，无需向前端交付服务令牌。

## 恢复与验收范围

`sudo python3 "$script" --backup` 创建真实 PG17 加密归档。保留对应密钥和归档的独立受控副本。恢复演练用 `tests/identity/pg/check.sh` 在一次性 PG17 中创建空目标、解密恢复并验证数据；生产迁移及生产恢复均不在此入口。SQLite 的既有一致性备份工具和验证见 `../bsv1/`。

CI 的真实 HTTP 试验涵盖登入、开桌、加单、提交未付款订单、跨店拒绝、供货及督查授权、撤权和中央写入阻断。PG17 候选收货守恒与独立复核由预检测试替身执行。完整中央接口落地和 Lighthouse 实机回切另行验收。
