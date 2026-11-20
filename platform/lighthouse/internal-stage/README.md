# Lighthouse 内部集成测试版

仅面向既有北京 Lighthouse 的 SSH 隧道。保留 8765、8767、其 systemd 单元和数据目录。新服务安装于 `/opt/bsv-all-internal-stage/releases/<sha>`，测试状态位于 `/var/lib/bsv-all-internal-stage`。全部监听 `127.0.0.1`。请只在受信任的主机和本机 SSH 客户端使用。未来 HTTPS 私有发布需要另行配置可信主机名、Secure Cookie 和访问门禁。

| 启动顺序 | 端口与入口 | 依赖和数据 |
|---|---|---|
| PostgreSQL 17 | 18764，专用 peer socket 及 SCRAM TCP | 独立实例与数据库 `bsv_identity_isolated_internal`。非超级用户拥有该测试库。仅目标库和测试角色可经 TCP 进入。 |
| 人员身份 R2 | 18761，`services.api.identity.api:app` | 独立锁定 venv。A 使用本机 PG，B 不配置。一次性应用已有候选迁移 `bsv_identity_0001`。隔离认证、双审核人及 AES-GCM 归档。 |
| 门店 POS | 18762，`services/api/bsv1/app.py` | Python 标准库。新 SQLite 与仓库生成的合成 V9。服务端对 R2 逐次鉴权。BSVT 测试别名；下单仅允许未付款模式。 |
| 供货和督查 | 18763，`services.api.supply.main:app` | 另一套锁定 venv。仅接 B 身份源。A/C 目录及 D/E 事实服务当前未接，写入返回 503。 |
| 私有入口 | 18760，`ingress:app` | 同源转发 POS、`/staff`、`/hq`、`/supply-ui/hq/supply`、`/supply-ui/inspector/supply`。`/cocktail/` 提供已有菜单文件。`/craft/` 返回 404。 |

## 前台发布与验收

Ubuntu 24.04 需具备 `sudo`、`python3.12-venv`、`ss` 和 `/usr/lib/postgresql/17/bin` 的 PG17 客户端及服务端。发布不安装系统包。请用现有私有仓库 Deploy Key 拉取代码，使用已批准的完整 SHA 创建独立工作树。两个旧服务及其端口必须在发布前处于运行状态。`18760–18764` 只允许受管理实例绑定 `127.0.0.1`。

使用有私有仓库读取权限的 GitHub 客户端导出已成功的 PR 运行证据。把 `ci-proof.json` 传到主机受控路径，核对其链接、工作流和批准的不可变 SHA。主机无需 GitHub 写入令牌。`bsvctl.py` 校验证据的结构和内容，由经营负责人核验证据来源和批准发布。

```bash
# 从能够读取此私有仓库的客户端执行，再通过安全渠道传输 ci-proof.json
# CI_RUN_ID 取最终 PR 的成功 pull_request 运行编号
gh run view "$CI_RUN_ID" -R Ethancao258/bsv-all-platform \
  --json url,headSha,event,status,conclusion,workflowName,jobs > ci-proof.json
```

```bash
# 在 Lighthouse 上从批准 SHA 对应的干净工作树执行
ctl=platform/lighthouse/internal-stage/bsvctl.py
python3 "$ctl" status
sudo python3 "$ctl" deploy --sha "$APPROVED_SHA" --approve-isolated \
  --ci-proof "$HOME/ci-proof.json" --request-id ISSUE-9 \
  --module identity-api --module identity-hq-ui --module store-pos --module deployment-config
python3 "$ctl" verify
```

发布命令只调用本地受控部署代码。发生变更时先暂停五个隔离单元中的应用写入，保留隔离 PG17 连接，创建加密 PG 与一致性 POS 备份，再切换版本。验证失败会恢复原版本并重新检查其路由与端口。已有库和服务配置继续保留。迁移目录变化会阻止本路径升级。

`verify` 检查两个旧服务、五个隔离监听、本地 HTTP 路由、健康及匿名拒绝，成功显示 `RELEASE_HEALTH_OK` 和 `VERIFY_OK`。业务验收另行执行一次，明确批准通过真实 HTTP 写入临时合成授权及未付款测试记录。

```bash
stage=/opt/bsv-all-internal-stage/current
sudo "$stage/identity/bin/python" "$stage/src/platform/lighthouse/internal-stage/acceptance.py" \
  --expected-sha "$APPROVED_SHA" --execute-isolated
```

`STAGING_ACCEPTED` 是本次内部隔离验收结果。中央 D/E 写入仍标为 `BLOCKED`。仅供登录人员的浏览器可在已有 SSH 隧道下打开 `http://127.0.0.1:18760/`。测试身份与 POS PIN 由验收脚本在主机读取，输出不含凭据。旧码 `bsv1_pos,SYNTH-STAGE-POS-01,TRA0001` 的已有精确映射按幂等结果处理。

## 安全回切与检查点

```bash
# 在原本用于批准发布的干净工作树中执行
sudo python3 platform/lighthouse/internal-stage/bsvctl.py rollback
```

回切前同样生成检查点，只更改这五个隔离测试单元。原版本存在时启动并核查其健康，无原版本时停止测试服务并保留数据。代码回切沿用已有隔离库，快照不自动写回。若半途退出，激活日志保留原版本，下一次受控操作会恢复原先状态。若缺少受管活动版本但存在旧库文件，先由操作者核对状态，部署会停止。用 `journalctl -u 'bsv-all-internal-stage@*.service'` 查阅隔离服务的启动日志。

`sudo python3 platform/lighthouse/internal-stage/stage.py --backup` 生成独立手动检查点，带 `CHECKPOINT_READY` 和根账户只读的 `recovery/<时间>-<标识>/receipt.json` 路径。PG17 归档使用 AES-GCM，检查点复核加密完整性和 SHA-256；SQLite 采用在线备份 API，并核验快照 `PRAGMA quick_check` 和 SHA-256。按受控流程分别保存归档和密钥。部署前检查点暂停隔离应用写入，手动检查点只保证两个单独数据库各自一致。`tests/identity/pg/check.sh` 在真正的临时 PG17 目标中完成解密恢复与合成数据校验。生产级恢复演练与 Lighthouse 实机回切仍为 `HOST_NOT_RUN`，需以本机证据更新记录。

一句话自动启动 Codex、从 GitHub 自动触发主机和生产数据迁移为 `NOT_CONNECTED`。`bsvctl.py` 只提供已经实现的人工批准入口。
