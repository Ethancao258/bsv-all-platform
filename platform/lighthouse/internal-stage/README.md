# Lighthouse V4.1 内部集成测试版

仅面向既有北京 Lighthouse 的 SSH 隧道。保留 8765、8767、其 systemd 单元和数据目录。新服务安装于 `/opt/bsv-all-internal-stage/releases/<sha>`，测试状态位于 `/var/lib/bsv-all-internal-stage`。全部监听 `127.0.0.1`。请只在受信任的主机和本机 SSH 客户端使用。未来 HTTPS 私有发布需要另行配置可信主机名、Secure Cookie 和访问门禁。

| 启动顺序 | 端口与入口 | 依赖和数据 |
|---|---|---|
| PostgreSQL 17 | 18764，专用 peer socket 及 SCRAM TCP | 独立实例与数据库 `bsv_identity_isolated_internal`。非超级用户拥有该测试库。仅目标库和测试角色可经 TCP 进入。 |
| 人员身份及学院 | 18761，`services.api.identity.api:app` | 独立锁定 venv。A 使用本机 PG，B 不配置。仅隔离环境依次应用 `bsv_identity_0001` 与 `bsv_academy_0002`。隔离认证、双审核人及 AES-GCM 归档。 |
| 门店 POS | 18762，`services/api/bsv1/app.py` | 保留 SQLite 和已有合成 V9。V4.1 启动启用设备核验，身份服务逐次核对门店资格、权限、确认班次和设备。仅可保存未付款演练订单。 |
| 供货和督查 | 18763，`services.api.supply.main:app` | 另一套锁定 venv。仅接 B 身份源。A/C 目录及 D/E 事实服务当前未接，写入返回 503。 |
| 私有入口 | 18760，`ingress:app` | 同源转发 POS、`/staff`、`/hq`、`/supply-ui/hq/supply`、`/supply-ui/inspector/supply`。`/cocktail/` 提供已有菜单文件。`/craft/` 返回 404。 |

## 前台发布与验收

Ubuntu 24.04 需具备 `sudo`、`python3.12-venv`、`ss` 和 `/usr/lib/postgresql/17/bin` 的 PG17 客户端及服务端。发布不安装系统包。请用现有私有仓库 Deploy Key 拉取代码，使用已批准的完整 SHA 创建独立工作树。两个旧服务及其端口必须在发布前处于运行状态。`18760–18764` 只允许受管理实例绑定 `127.0.0.1`。

用有仓库读取权限的 GitHub CLI 客户端从 GitHub 直接导出已成功的 PR 运行。候选版本的发布器核对不可变 SHA 和全部八项作业。经现有 SSH 通道将导出文件传到主机，由经营负责人核对其来源并批准。主机使用既有只读 Deploy Key，无需保存 GitHub CLI 令牌。

```bash
# 从候选提交工作树和已登录 gh 的客户端执行
python3 platform/lighthouse/internal-stage/bsvctl.py ci-evidence \
  --sha "$APPROVED_SHA" --run "$CI_RUN_ID" > ci-proof.json
```

```bash
# 在 Lighthouse 上从批准 SHA 对应的干净工作树执行
ctl=platform/lighthouse/internal-stage/bsvctl.py
python3 "$ctl" status
sudo python3 "$ctl" deploy --sha "$APPROVED_SHA" --approve-isolated \
  --ci-proof "$HOME/ci-proof.json" --request-id ISSUE-11 \
  --module identity-api --module identity-hq-ui --module store-pos --module deployment-config
python3 "$ctl" verify
```

发布时先暂停隔离应用写入，保留隔离 PG17 连接，生成 PG 加密归档、POS 一致性快照和已有学院媒体私有副本。发布器仅接受原迁移目录不变或只增加已审核的学院 `20261120_0002_academy.py`，并记录真实 Alembic 修订。验证失败会恢复前一版本并复查路由与端口。V3 的数据、旧 POS 码映射和系统配置留在原有位置。

`verify` 检查两个旧服务、五个隔离监听、本地 HTTP 路由、健康及匿名拒绝，成功显示 `RELEASE_HEALTH_OK` 和 `VERIFY_OK`。业务验收另行执行一次，明确批准通过真实 HTTP 写入临时合成授权及未付款测试记录。

```bash
stage=/opt/bsv-all-internal-stage/current
sudo "$stage/identity/bin/python" "$stage/src/platform/lighthouse/internal-stage/acceptance_v41.py" \
  --expected-sha "$APPROVED_SHA" --execute-isolated
```

`V4_STAGING_ACCEPTED` 是本次内部隔离业务验收结果。中央 D/E 写入仍标为 `BLOCKED`。员工经已有 SSH 隧道打开 `http://127.0.0.1:18760/`，登录后进入学院，完成门店相应版本课程和实操。由负责人完成班次审批，再由员工确认，才进入已注册点单终端。旧码 `bsv1_pos,SYNTH-STAGE-POS-01,TRA0001` 的已有精确映射保留。验收输出不含设备令牌与账号凭据。

学院媒体保存在隔离服务账户的私有目录。没有能实际扫描文件的 `clamdscan` 时，服务明确拒绝上传。部署器不安装扫描程序或配置外部对象存储。真实课件、视频和员工资料仍需单独的隐私、版权、存储、备份和访问审批。

## 安全回切与检查点

```bash
# 在原本用于批准发布的干净工作树中执行
sudo python3 platform/lighthouse/internal-stage/bsvctl.py rollback
```

在 V4.1 候选工作树执行回切。回切前同样生成检查点，只更改五个隔离单元。恢复 V3 代码时保留新增学院表、数据、POS SQLite 和媒体，V3 启动器恢复原有设备策略。回切不执行数据库降级，也不会自动写回快照。中断时保留激活日志供下一次受控操作恢复。若缺少受管活动版本但存在旧库文件，部署会停下来。用 `journalctl -u 'bsv-all-internal-stage@*.service'` 查看隔离服务日志。

以下为可单独执行的备份与恢复检查命令。使用前一条输出中完整的 `checkpoint` 路径。

```bash
stage_tool=platform/lighthouse/internal-stage/stage.py
sudo python3 "$stage_tool" --backup
sudo python3 "$stage_tool" --recovery-check "$CHECKPOINT_RECEIPT"
```

`CHECKPOINT_READY` 回执受根账户保护。恢复检查实际校验 AES-GCM、PG 文件 SHA-256、SQLite `PRAGMA quick_check` 和学院媒体指纹，成功显示 `RECOVERY_CHECK_READY`。按受控流程分别保存归档和密钥。部署前检查点暂停隔离写入，手动备份不承诺跨库同一时点。`tests/identity/pg/check.sh` 在真正的临时 PG17 目标中执行解密恢复与合成数据校验。生产恢复与 V4.1 Lighthouse 实机回切仍须实际执行后更新证据。

一句话自动启动 Codex、从 GitHub 自动触发主机和生产数据迁移为 `NOT_CONNECTED`。`bsvctl.py` 只提供已经实现的人工批准入口。


## BSV V9 酒水Excel私有资料更新

原始附件不进入GitHub。运行时私有版本存储位于 `/var/lib/bsv-all-internal-stage/pos/catalog`（随程序发布不删除），产品图片位于 `/var/lib/bsv-all-internal-stage/pos/product-media/{product_id}/{原文件名}`。两者由POS服务账户 `bsvint-pos` 独占读写，目录0700，Excel/清单0600。`BSV_PRODUCT_MEDIA_ROOT` 指向该持久目录，图片查找优先读取持久目录，并只读回退旧 release 素材路径。活动指针记录SHA256、前一版本、导入时间及人工锁。目录首次使用由POS账户创建；部署器只允许对已登记的受管配置作明确变更，按既有差异比较流程拒绝未知密钥/变更。

安全导入流水线（`BSV_IMPORT_ROOT=/var/lib/bsv-all-internal-stage/pos/imports`，归档与目录活动版本分开；使用同一 V9 解析/验证器）：

```bash
sudo -u bsvint-pos env PYTHONPATH=/opt/bsv-all-internal-stage/current/src/services/api/bsv1 \
  BSV_CATALOG_DIR=/var/lib/bsv-all-internal-stage/pos/catalog \
  BSV_IMPORT_ROOT=/var/lib/bsv-all-internal-stage/pos/imports \
  python3 -m bsv_v9_catalog_store archive /var/lib/bsv-all-internal-stage/pos/imports/incoming/catalog.xlsx \
  --store-dir /var/lib/bsv-all-internal-stage/pos/catalog
# 用返回的 SHA 依次调用 preview、validate、commit-candidate；确认审批后才 publish。
```

`archive/preview/validate/commit-candidate` 不切换活动版本，不修改 POS SQLite。只有受控 `publish` 会复用现有事务同步与活动版本指针；`rollback` 可恢复上一个有效目录版本。旧 `stage` 命令名保留，但现在仅执行安全归档与校验，不会顺带发布。手动上传的文件必须先经过受限目录和同一 SHA/七表/固定 ID校验；此处没有新增公网上传路由。

以下为人工上传方式。先从管理终端上传到服务器暂存位置，再在服务器通过POS账户运行同一Excel七表解析与SQLite事务校验。不要放进 `releases/<sha>`：

```bash
scp 'BSVALL酒水套餐数据库.xlsx' ubuntu@<已批准的Lighthouse主机>:/home/ubuntu/BSVALL酒水套餐数据库.xlsx
ssh ubuntu@<已批准的Lighthouse主机>
sudo install -d -o bsvint-pos -g bsvint-pos -m 0700 /var/lib/bsv-all-internal-stage/pos/imports/incoming
sudo install -o bsvint-pos -g bsvint-pos -m 0600 \\
  /home/ubuntu/BSVALL酒水套餐数据库.xlsx \\
  /var/lib/bsv-all-internal-stage/pos/imports/incoming/BSVALL酒水套餐.xlsx
sudo -u bsvint-pos env \\
  PYTHONPATH=/opt/bsv-all-internal-stage/current/src/services/api/bsv1 \\
  BSV_CATALOG_DIR=/var/lib/bsv-all-internal-stage/pos/catalog \\
  BSV_IMPORT_ROOT=/var/lib/bsv-all-internal-stage/pos/imports \\
  BSV_V9_XLSX=/var/lib/bsv-all-internal-stage/pos/synthetic-v9.xlsx \\
  /usr/bin/python3 -m bsv_v9_catalog_store stage \\
  /var/lib/bsv-all-internal-stage/pos/imports/incoming/BSVALL酒水套餐.xlsx \\
  --store-dir /var/lib/bsv-all-internal-stage/pos/catalog
# 用 stage 返回的 SHA256 做预览、校验、人工提交，然后才发布：
SHA256="从 stage 输出复制的64位SHA256"
sudo -u bsvint-pos env BSV_IMPORT_ROOT=/var/lib/bsv-all-internal-stage/pos/imports PYTHONPATH=/opt/bsv-all-internal-stage/current/src/services/api/bsv1 \\
  python3 -m bsv_v9_catalog_store preview "$SHA256" --store-dir /var/lib/bsv-all-internal-stage/pos/catalog
sudo -u bsvint-pos env BSV_IMPORT_ROOT=/var/lib/bsv-all-internal-stage/pos/imports PYTHONPATH=/opt/bsv-all-internal-stage/current/src/services/api/bsv1 \\
  python3 -m bsv_v9_catalog_store validate "$SHA256" --store-dir /var/lib/bsv-all-internal-stage/pos/catalog
sudo -u bsvint-pos env BSV_IMPORT_ROOT=/var/lib/bsv-all-internal-stage/pos/imports PYTHONPATH=/opt/bsv-all-internal-stage/current/src/services/api/bsv1 \\
  python3 -m bsv_v9_catalog_store commit-candidate "$SHA256" --store-dir /var/lib/bsv-all-internal-stage/pos/catalog
sudo -u bsvint-pos env BSV_IMPORT_ROOT=/var/lib/bsv-all-internal-stage/pos/imports PYTHONPATH=/opt/bsv-all-internal-stage/current/src/services/api/bsv1 \\
  python3 -m bsv_v9_catalog_store publish "$SHA256" --database /var/lib/bsv-all-internal-stage/pos/synthetic.sqlite3 \\
  --store-dir /var/lib/bsv-all-internal-stage/pos/catalog
sudo -u bsvint-pos env BSV_CATALOG_DIR=/var/lib/bsv-all-internal-stage/pos/catalog \\
  /usr/bin/python3 -m bsv_v9_catalog_store status --store-dir /var/lib/bsv-all-internal-stage/pos/catalog
```

回退：以同样的 `PYTHONPATH`、`BSV_CATALOG_DIR`、`BSV_V9_XLSX` 运行 `/usr/bin/python3 -m bsv_v9_catalog_store rollback --database /var/lib/bsv-all-internal-stage/pos/synthetic.sqlite3 --store-dir /var/lib/bsv-all-internal-stage/pos/catalog`。发布会设置人工版本锁；暂时没有已实现的CloudBase自动下载器或每日05:00任务。解除锁的CLI只解除覆盖保护，不会自行启动云同步。需要CloudBase官方私有对象身份、Bucket/object fileID验证和服务端定时同步后再启用。

资料查询必须通过POS登录后使用稳定契约 `/api/v1/catalog/products`、`/api/v1/catalog/products/{product_id}`、`/api/v1/catalog/products/{product_id}/recipe`；旧 `/api/catalog/*` 接口保留兼容。请求不创建订单。产品图片通过现有私有图片目录和同一登录会话读取。资料可查与可售分离，人工确认内容、商品上架、门店及报价授权前保持不可销售。

本说明为代码交付方法，不是已在Lighthouse执行的部署记录。当前主机安装、初次Excel启用和浏览器验收均为 `HOST_NOT_RUN`。
