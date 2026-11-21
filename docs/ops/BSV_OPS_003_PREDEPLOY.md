# BSV-OPS-003｜离线补充包与 OrcaTerm 操作单

## 交付边界

源码仍使用目标 `f00371ccd1c233caf8eea97398bf981cf7d65dd0` 的 PR #34 签名构件；本补充包只含完整离线 Python wheelhouse、Cosign 2.4.1 验签器、其官方发布签名材料、Sigstore 生产 TUF 信任材料和文件 SHA 清单，不重复包含源码 Git bundle。发布构件来源为当前 PR #34 release workflow 同次运行生成的签名构件，签名 workflow 是本仓库 `bsv-ops-003-release.yml` 的 PR #34 merge ref；源码 CI 证明固定为成功 run `44894443077` 的九个必需 job。

因为 Lighthouse 架构尚未读取，CI 分别在 Ubuntu 24.04/Python 3.12 的原生 `amd64` 和 `arm64` runner 构建及断网安装。主机只根据 `uname -m` 选择一份；其他架构必须停止，不准借用或软链接另一架构/旧版 venv。原 c51 与 f003 的 `requirements.lock` 相同；f003 新增 `services/api/customer_growth/requirements.stage.lock`（qrcode 8.2、Pillow 11.3.0），由 identity 的新 venv 同时安装。故每份 wheelhouse 都完整包含 identity lock、growth stage lock 和 supply lock 三份精确锁定文件，不只提供两个新 wheel。`pip check` 是成功条件。

`c51 → f003` 没有迁移文件差异；两版都含 `bsv_identity_0001` 与 `bsv_academy_0002`。数据库修订应保持现有值，不运行 CloudBase 或其他生产迁移。f003 的部署器保留旧配置并只按其白名单追加隔离增长配置，使用独立新 venv，并把增长候选 SQLite 纳入现有隔离备份/完整性检查。f003 仍由 `stage.py` 创建新环境；不要复制旧 venv。

## OrcaTerm AI 执行步骤

仅在经营者把**新架构补充包**放入 `/home/ubuntu/bsv-ops-003-verify/predeploy-supplement/` 后执行；原发布 ZIP 不需要重新下载或上传。先核实现场状态，任何现状与以下已报告基线不符即 STOP：运行 SHA `c51b58d67dabae53afcdf9851a80cdc93d4200f6`、回滚 SHA `0e8b3c00544ccd533eebd1258598f2622c5b0984`、`pending_activation=false`、五个隔离服务正常，8765/8767 旧服务正常。不能从旧对话状态推定当前仍相同。

1. 从 supplement 文件名选定 `amd64` 或 `arm64`，并执行 `uname -m`。`x86_64` 对应 amd64，`aarch64` 对应 arm64；其他值 STOP。确认 PR #34 对应的补充 artifact 名、本次 PR #34 release run ID 与文件 SHA sidecar 一致。补充 artifact 的 Actions 页面及文件名会列在本任务的最终交付中。将 `SUPP` 设为 `.tar` 路径，`ARCH_DIR` 设为上一步说明的全新空解包目录，`ROOT="$ARCH_DIR"`。
2. 从 supplement tar 中仅用 `tar -xOf` 读取启动验签材料到全新私有临时目录：

   ```bash
   export BOOT=/home/ubuntu/bsv-ops-003-verify/cosign-bootstrap
   install -d -m 700 "$BOOT"
   tar -xOf "$SUPP" bsv-ops-003-host-supplement/bootstrap/cosign > "$BOOT/cosign"
   tar -xOf "$SUPP" bsv-ops-003-host-supplement/bootstrap/release-cosign.pub > "$BOOT/release-cosign.pub"
   tar -xOf "$SUPP" bsv-ops-003-host-supplement/bootstrap/cosign-release.sig.b64 > "$BOOT/cosign-release.sig.b64"
   chmod 700 "$BOOT/cosign"
   sha256sum "$BOOT/release-cosign.pub"
   base64 -d "$BOOT/cosign-release.sig.b64" > "$BOOT/cosign-release.sig"
   openssl dgst -sha256 -verify "$BOOT/release-cosign.pub" -signature "$BOOT/cosign-release.sig" "$BOOT/cosign"
   "$BOOT/cosign" version
   ```

   公钥 SHA256 必须等于 `f4cea466e5e887a45da5031757fa1d32655d83420639dc1758749b744179f126`，Cosign 自报版本及架构必须是 2.4.1 与目标 CPU。任一不符 STOP。该固定公钥摘要来自 PR 中锁定的官方 `sigstore/cosign-installer` 源码，installer 会以同一公钥校验官方 Cosign 发布二进制。
3. 在运行任何包内程序前，使用系统 Python 安全解包。以下命令只允许预期前缀下的常规文件/目录，拒绝路径穿越、重复成员、链接、设备和超过 700 MiB 的展开：

   ```bash
   export EXTRACT=/home/ubuntu/bsv-ops-003-verify/predeploy-supplement/verified-unpacked
   test ! -e "$EXTRACT" && install -d -m 700 "$EXTRACT"
   python3 - "$SUPP" "$EXTRACT" <<'PY'
   import os, pathlib, sys, tarfile
   archive_path, target = sys.argv[1:]
   root = pathlib.Path(target).resolve()
   seen, total = set(), 0
   with tarfile.open(archive_path, 'r:') as archive:
       members = archive.getmembers()
       for member in members:
           path = pathlib.PurePosixPath(member.name)
           if (path.is_absolute() or '..' in path.parts or not member.name.startswith('bsv-ops003-host-supplement/')
                   or member.name in seen or not (member.isdir() or member.isreg())):
               raise SystemExit('STOP: unsafe supplement archive member')
           seen.add(member.name)
           total += member.size
           if total > 700 * 1024 * 1024:
               raise SystemExit('STOP: supplement expands beyond 700 MiB')
       for member in members:
           relative = pathlib.PurePosixPath(member.name).relative_to('bsv-ops003-host-supplement')
           destination = root.joinpath(*relative.parts)
           if member.isdir():
               destination.mkdir(parents=True, exist_ok=True, mode=0o700)
           else:
               destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
               source = archive.extractfile(member)
               if source is None:
                   raise SystemExit('STOP: missing archive payload')
               fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, member.mode & 0o755)
               with os.fdopen(fd, 'wb') as output:
                   output.write(source.read(member.size + 1))
   PY
   export ARCH_DIR="$EXTRACT"
   ```

   Then use the packaged TUF repository mirror and Cosign's bootstrap trust root, with `HOME` pointing to a new offline directory, to run `cosign initialize --mirror="file://$ARCH_DIR/trust/tuf-repo-cdn.sigstore.dev"`; the resulting `$HOME/.sigstore/root/targets/trusted_root.json` must byte-match `$ROOT/trust/trusted_root.json`. This replays root rotations 1–N and validates the timestamp, snapshot, targets and target hashes through TUF; do not trust only the root JSON packaged beside the supplement.
4. 用这个经官方签名验证的 Cosign、已通过本地 TUF 链验证的 trusted root，离线验 supplement 外层 `.sigstore.json`。必须使用 Cosign **new bundle format**（该 release workflow 已显式生成），issuer 必须是 `https://token.actions.githubusercontent.com`，certificate identity 必须精确为：

   `https://github.com/Ethancao258/bsv-all-platform/.github/workflows/bsv-ops-003-release.yml@refs/pull/34/merge`

   验签及 SHA 命令如下；通过外层签名后，才可执行包内验证器检查文件清单：

   ```bash
   cosign verify-blob --new-bundle-format --offline --trusted-root "$ROOT/trust/trusted_root.json" \
     --bundle "$SUPP.sigstore.json" --certificate-oidc-issuer https://token.actions.githubusercontent.com \
     --certificate-identity 'https://github.com/Ethancao258/bsv-all-platform/.github/workflows/bsv-ops-003-release.yml@refs/pull/34/merge' "$SUPP"
   (cd "$(dirname "$SUPP")" && sha256sum --check "$(basename "$SUPP").sha256")
   python "$ARCH_DIR/tools/ops003_predeploy.py" verify-supplement-archive --archive "$SUPP"
   python "$ARCH_DIR/tools/ops003_predeploy.py" verify-supplement-tree --root "$ARCH_DIR"
   ```
5. 将原源发布包作为独立输入，用同一 Cosign/root 离线验证 `bsv-all-f00371ccd1c233caf8eea97398bf981cf7d65dd0.tar.sigstore.json`。同样使用 `--new-bundle-format --offline --trusted-root`；issuer 不变，certificate identity 必须精确为：

   `https://github.com/Ethancao258/bsv-all-platform/.github/workflows/bsv-ops-003-release.yml@refs/pull/34/merge`

   验证 `.sha256`，再运行补充包内 `tools/ops003_predeploy.py verify-source`，参数为 `--cosign <COSIGN_PATH> --trusted-root <SUPPLEMENT_ROOT>/trust/trusted_root.json --bundle <RELEASE_DIR>/bsv-all-f00371ccd1c233caf8eea97398bf981cf7d65dd0.tar --sha256 <同名.tar.sha256> --sigstore <同名.tar.sigstore.json>`。该检查核对完整 SHA、tree、逐文件 Git blob/mode、manifest 及 CI run `44894443077` 的九个成功 job。不得在 f003 checkout 中寻找或执行 `ops003_release.py`；使用经过 PR #34 签名 supplement 验证过的 `tools/` 副本。
6. `bsvctl status` 与发布前的 `bsvctl verify` 必须分别确认部署/回滚版本、无待激活事务、旧 8765/8767 运行、五个服务仅监听 loopback、磁盘与目录权限无异常。确认数据库迁移修订不变。`bsvctl deploy` 自身还会锁定、执行 `stage.preflight`、建立并检查加密 PG17/POS SQLite/增长 SQLite/媒体检查点，创建全新 venv 并对所有 wheel 离线安装。以上任何一项失败 STOP，保持旧 current。
7. 只有经营者此前已明确批准此**隔离合成版本**后，执行一次部署。示例中变量由现场 `uname -m` 结果选择：

   ```bash
   export SHA=f00371ccd1c233caf8eea97398bf981cf7d65dd0
   export SRC=/home/ubuntu/bsv-ops-003-verify
   export SUPP=/home/ubuntu/bsv-ops-003-verify/predeploy-supplement/VERIFIED_ARCH_PACKAGE
   export ARCH_DIR=/home/ubuntu/bsv-ops-003-verify/predeploy-supplement/VERIFIED_ARCH_DIR
   export CHECKOUT=/home/ubuntu/bsv-ops-003-verify/f003-source
   export WHEELHOUSE="$ARCH_DIR/wheelhouse"
   # 已由经签名验证的 release manifest 验过 source.gitbundle 与 ci-proof.json 后才恢复：
   tar -xOf "$SRC/bsv-all-$SHA.tar" source.gitbundle > "$SRC/source.gitbundle"
   tar -xOf "$SRC/bsv-all-$SHA.tar" ci-proof.json > "$SRC/ci-proof.json"
   git clone --branch bsv-ops-003-release-target "$SRC/source.gitbundle" "$CHECKOUT"
   git -C "$CHECKOUT" remote set-url origin https://github.com/Ethancao258/bsv-all-platform.git
   test "$(git -C "$CHECKOUT" rev-parse HEAD)" = "$SHA"
   test -z "$(git -C "$CHECKOUT" status --porcelain)"
   sudo env PIP_NO_INDEX=1 PIP_FIND_LINKS="$WHEELHOUSE" \
     /usr/bin/python3 "$CHECKOUT/platform/lighthouse/internal-stage/bsvctl.py" deploy \
     --sha "$SHA" --approve-isolated --ci-proof "$SRC/ci-proof.json" --request-id ISSUE-32 \
     --module deployment-config --module identity-api --module store-pos \
     --module customer-growth --module guest-menu
   ```

8. 运行 `sudo /usr/bin/python3 "$CHECKOUT/platform/lighthouse/internal-stage/bsvctl.py" verify`；确认 `CURRENT_SHA` 精确匹配 f003、`pending_activation=false`、`RELEASE_HEALTH_OK`、`VERIFY_OK`。按批准的隔离合成验收再运行：

   ```bash
   sudo /opt/bsv-all-internal-stage/current/identity/bin/python \
     /opt/bsv-all-internal-stage/current/src/platform/lighthouse/internal-stage/acceptance_v41.py \
     --expected-sha f00371ccd1c233caf8eea97398bf981cf7d65dd0 --execute-isolated
   ```

   只接受 `V4_STAGING_ACCEPTED` 且结果含 `GROWTH_POS=PASS`。用本机 loopback HTTP 检查 `/member/`、`/staff/growth/` 和工作台、POS、学院、总部、菜单；确认旧服务 8765/8767 仍 active。报告实际主机 SHA/服务/备份回执；`HOST_RECOVERY=NOT_RUN` 必须如实保留，未做恢复演练不可改写为通过。

若部署或验收失败，立即停止进一步写入，查询 `bsvctl status`。若 f003 仍 active，使用现有 `sudo .../bsvctl.py rollback`，然后再次 `verify`，确认 current 恢复为部署前版本且两个旧服务仍运行。不要删除检查点、改数据库修订、修改旧服务或用手工 symlink 回切。验收不通过前禁止对经营者宣称升级成功。

## CI 通过条件与未执行事项

GitHub predeploy job 必须在原生 amd64 和 arm64 runner 分别通过：真实 PR #34 源包离线 Sigstore 验签和 TUF 可信链、签名篡改拒绝、固定 commit/tree/九项 CI 验证、三份依赖锁的全新 venv 离线安装及 `pip check`、缺 wheel 失败拒绝、包内文件哈希与补充包篡改拒绝、官方 Cosign 发布签名。构件分别命名为 `bsv-ops-003-host-supplement-<arch>-<run_id>`，外层 tar 自带 SHA256、Sigstore 签名 bundle 和 Build Provenance；保留 7 天。由于 host CPU 尚未知，必须先现场选择对应包。

`HOST_NOT_RUN`：Codex 没有执行腾讯云服务器命令；真实 systemd/PG/SQLite checkpoint、现场目录权限、进程资源、HTTP、V4.1/Growth POS 和 SSH 隧道浏览器仍由 OrcaTerm AI 按以上顺序验证。任何未通过的主机门禁须停止部署并回报证据。
