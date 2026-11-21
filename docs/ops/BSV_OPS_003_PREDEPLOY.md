# BSV-OPS-003｜H 版本隔离发布操作单

## 固定发布证据

- 目标 H：`cb06be66e78d92b8921fc3103b12bdbdc55284f8`
- H 的九项 CI：<https://github.com/Ethancao258/bsv-all-platform/actions/runs/44922120417>
- 新源码由 PR #34 的 `bsv-ops-003-release.yml` 在 `refs/pull/34/merge` 签名，使用 Cosign new bundle format。
- 目标主机架构为运营者确认的 `x86_64`，本次只生成 amd64 补充包。
- f003 与 H 的三份锁文件逐字节一致：identity `832e54fa316c94d0de5d4e4615af94fc87ad98e715c19bf6cf5b8b2faff8e997`、growth `60dcd51713cdd296db0c9d7a4f1153053003dc436213f75833621815d801f635`、supply `e31815c229a1089675bc5d034a41132b2384f67e1e26fbd55c125311567e4510`。新补充包不重复携带 wheelhouse；仅当旧 amd64 补充包验签、整体文件清单及 wheel 哈希通过时，复用旧 wheelhouse。
- 旧 wheelhouse 来源：run `44913890434`，artifact `14710029781`，补充包 SHA256 `2b65e83493594d2bc1948e407499169264a44c36ba66510bb498a7515eff750a`。禁止复制旧 venv。
- Codex 未连接 Lighthouse。主机服务、磁盘、备份、systemd、PostgreSQL 与 HTTP 仍须由 OrcaTerm 重新读取；任何基线不符即停止。旧 8765/8767 与 f003 失败目录必须保留。

## OrcaTerm AI 执行指令

运营者从 PR #34 的同一次成功 `bsv-ops-003-release` run 下载两个构件并放入 `/home/ubuntu/bsv-ops-003-verify-next/incoming/`：

- `bsv-all-cb06be66e78d92b8921fc3103b12bdbdc55284f8.tar`、同名 `.sha256`、`.sigstore.json`
- `bsv-ops-003-host-supplement-amd64.tar`、同名 `.sha256`、`.sigstore.json`

补充包发布门禁小于 100,000,000 字节，不包含 wheelhouse。先按以下命令重验旧 wheelhouse，再验新构件。任何命令失败立即停止，不修改主机。

```bash
set -euo pipefail
H=cb06be66e78d92b8921fc3103b12bdbdc55284f8
OLD=c51b58d67dabae53afcdf9851a80cdc93d4200f6
PREVIOUS=0e8b3c00544ccd533eebd1258598f2622c5b0984
BASE=/home/ubuntu/bsv-ops-003-verify
NEXT=/home/ubuntu/bsv-ops-003-verify-next
INCOMING="$NEXT/incoming"
OLD_ROOT="$BASE"
OLD_SUPP="$BASE/bsv-ops-003-host-supplement-amd64.tar"
COSIGN="$OLD_ROOT/bootstrap/cosign"
OLD_TOOLS="$OLD_ROOT/tools"
SUPP="$INCOMING/bsv-ops-003-host-supplement-amd64.tar"
RELEASE="$INCOMING/bsv-all-$H.tar"
test "$(uname -m)" = x86_64
test -x "$COSIGN" -a -s "$OLD_ROOT/supplement-manifest.json" -a -d "$OLD_ROOT/wheelhouse"
test -s "$OLD_ROOT/trust/trusted_root.json"
test -s "$SUPP" -a -s "$SUPP.sha256" -a -s "$SUPP.sigstore.json"
test -s "$RELEASE" -a -s "$RELEASE.sha256" -a -s "$RELEASE.sigstore.json"
test "$(stat -c %s "$SUPP")" -lt 100000000

# Recheck the previously accepted wheelhouse: exact archive SHA/signature and every extracted file hash.
printf '%s  %s\n' 2b65e83493594d2bc1948e407499169264a44c36ba66510bb498a7515eff750a "$OLD_SUPP" | sha256sum -c -
"$COSIGN" verify-blob --new-bundle-format --offline --trusted-root "$OLD_ROOT/trust/trusted_root.json" \
  --bundle "$OLD_SUPP.sigstore.json" --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity 'https://github.com/Ethancao258/bsv-all-platform/.github/workflows/bsv-ops-003-release.yml@refs/pull/34/merge' "$OLD_SUPP"
(cd "$(dirname "$OLD_SUPP")" && sha256sum --check "$(basename "$OLD_SUPP").sha256")
OPS003_SOURCE_ARTIFACT_RUN=44913890434 python3 "$OLD_TOOLS/ops003_predeploy.py" verify-supplement-archive --archive "$OLD_SUPP"
OPS003_SOURCE_ARTIFACT_RUN=44913890434 python3 "$OLD_TOOLS/ops003_predeploy.py" verify-supplement-tree --root "$OLD_ROOT"
find "$OLD_ROOT/wheelhouse" -maxdepth 1 -type f -name '*.whl' -print -quit | grep -q .

# Verify the new supplement signature before extraction. Extraction allows only regular files/directories.
(cd "$(dirname "$SUPP")" && sha256sum --check "$(basename "$SUPP").sha256")
"$COSIGN" verify-blob --new-bundle-format --offline --trusted-root "$OLD_ROOT/trust/trusted_root.json" \
  --bundle "$SUPP.sigstore.json" --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity 'https://github.com/Ethancao258/bsv-all-platform/.github/workflows/bsv-ops-003-release.yml@refs/pull/34/merge' "$SUPP"
NEW_ROOT="$NEXT/verified-supplement"
test ! -e "$NEW_ROOT" && install -d -m 700 "$NEW_ROOT"
python3 - "$SUPP" "$NEW_ROOT" <<'PY'
import os, pathlib, sys, tarfile
archive_path, target = sys.argv[1:]
root = pathlib.Path(target).resolve()
seen, total = set(), 0
with tarfile.open(archive_path, 'r:') as archive:
    members = archive.getmembers()
    for member in members:
        path = pathlib.PurePosixPath(member.name)
        if (path.is_absolute() or '..' in path.parts or not member.name.startswith('bsv-ops003-host-supplement/')
                or member.name in seen or not (member.isdir() or member.isreg()) or member.issym() or member.islnk()):
            raise SystemExit('STOP: unsafe supplement archive member')
        seen.add(member.name)
        total += member.size
        if total > 95 * 1024 * 1024:
            raise SystemExit('STOP: supplement exceeds 95 MiB')
    for member in members:
        relative = pathlib.PurePosixPath(member.name).relative_to('bsv-ops003-host-supplement')
        destination = root.joinpath(*relative.parts)
        if member.isdir():
            destination.mkdir(parents=True, exist_ok=True, mode=0o700)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            source = archive.extractfile(member)
            if source is None:
                raise SystemExit('STOP: missing payload')
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, member.mode & 0o755)
            with os.fdopen(fd, 'wb') as output:
                body = source.read(member.size + 1)
                if len(body) != member.size:
                    raise SystemExit('STOP: member size mismatch')
                output.write(body)
PY
export OPS003_SOURCE_ARTIFACT_RUN="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["source_artifact_run_id"])' "$NEW_ROOT/supplement-manifest.json")"
COSIGN_HOME="$NEXT/cosign-offline-home"
install -d -m 700 "$COSIGN_HOME"
HOME="$COSIGN_HOME" "$COSIGN" initialize --mirror="file://$NEW_ROOT/trust/tuf-repo-cdn.sigstore.dev"
cmp "$NEW_ROOT/trust/trusted_root.json" "$COSIGN_HOME/.sigstore/root/targets/trusted_root.json"
"$COSIGN" verify-blob --new-bundle-format --offline --trusted-root "$NEW_ROOT/trust/trusted_root.json" \
  --bundle "$SUPP.sigstore.json" --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity 'https://github.com/Ethancao258/bsv-all-platform/.github/workflows/bsv-ops-003-release.yml@refs/pull/34/merge' "$SUPP"
python3 "$NEW_ROOT/tools/ops003_predeploy.py" verify-supplement-archive --archive "$SUPP"
python3 "$NEW_ROOT/tools/ops003_predeploy.py" verify-supplement-tree --root "$NEW_ROOT"
python3 - "$NEW_ROOT/wheelhouse-lock-compatibility.json" "$OLD_ROOT/supplement-manifest.json" <<'PY'
import json, pathlib, sys
proof, manifest = map(lambda p: json.loads(pathlib.Path(p).read_text()), sys.argv[1:])
assert proof['target_sha'] == 'cb06be66e78d92b8921fc3103b12bdbdc55284f8'
assert proof['base_sha'] == 'f00371ccd1c233caf8eea97398bf981cf7d65dd0'
assert proof['wheelhouse_reuse'] == 'BYTE_IDENTICAL_LOCKS_ONLY'
assert manifest['target_sha'] == proof['base_sha'] and manifest['target_arch'] == 'amd64'
assert len(proof['locks']) == 3 and all(row['identical'] for row in proof['locks'].values())
print('OLD_AMD64_WHEELHOUSE_LOCK_COMPATIBILITY_PASS')
PY

# Verify the exact H source, CI evidence, and current host baseline before deployment.
(cd "$(dirname "$RELEASE")" && sha256sum --check "$(basename "$RELEASE").sha256")
"$COSIGN" verify-blob --new-bundle-format --offline --trusted-root "$NEW_ROOT/trust/trusted_root.json" \
  --bundle "$RELEASE.sigstore.json" --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity 'https://github.com/Ethancao258/bsv-all-platform/.github/workflows/bsv-ops-003-release.yml@refs/pull/34/merge' "$RELEASE"
python3 "$NEW_ROOT/tools/ops003_predeploy.py" verify-source --cosign "$COSIGN" \
  --trusted-root "$NEW_ROOT/trust/trusted_root.json" --bundle "$RELEASE" \
  --sha256 "$RELEASE.sha256" --sigstore "$RELEASE.sigstore.json"
test ! -e /opt/bsv-all-internal-stage/activation.pending
test "$(sudo bsvctl status | python3 -c 'import json,sys; print(json.load(sys.stdin)["deployed_sha"])')" = "$OLD"
test "$(sudo bsvctl status | python3 -c 'import json,sys; print(json.load(sys.stdin)["rollback_target_sha"])')" = "$PREVIOUS"
sudo bsvctl verify
test "$(systemctl is-active bsv1-preview.service)" = active
test "$(systemctl is-active bsv-all-bsv1-stage.service)" = active

# Restore H locally from its signed Git bundle. No network fetch is used.
CHECKOUT="$NEXT/checkout-$H"
test ! -e "$CHECKOUT"
tar -xOf "$RELEASE" source.gitbundle > "$NEXT/source.gitbundle"
tar -xOf "$RELEASE" ci-proof.json > "$NEXT/ci-proof.json"
git clone --quiet --branch bsv-ops003-release-target "$NEXT/source.gitbundle" "$CHECKOUT"
git -C "$CHECKOUT" remote set-url origin https://github.com/Ethancao258/bsv-all-platform.git
test "$(git -C "$CHECKOUT" rev-parse HEAD)" = "$H"
test -z "$(git -C "$CHECKOUT" status --porcelain)"

# Single state-changing step: new venvs install only from the already verified offline wheelhouse.
sudo env PIP_NO_INDEX=1 PIP_FIND_LINKS="$OLD_ROOT/wheelhouse" PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_CONFIG_FILE=/dev/null \
  /usr/bin/python3 "$CHECKOUT/platform/lighthouse/internal-stage/bsvctl.py" deploy \
  --sha "$H" --approve-isolated --ci-proof "$NEXT/ci-proof.json" --request-id ISSUE-32 \
  --module deployment-config --module identity-api --module store-pos --module customer-growth --module guest-menu
sudo /usr/bin/python3 "$CHECKOUT/platform/lighthouse/internal-stage/bsvctl.py" verify
sudo /opt/bsv-all-internal-stage/current/identity/bin/python \
  /opt/bsv-all-internal-stage/current/src/platform/lighthouse/internal-stage/acceptance_v41.py \
  --expected-sha "$H" --execute-isolated
```

仅当 `CURRENT_SHA=H`、`pending_activation=false`、`RELEASE_HEALTH_OK`、`VERIFY_OK`、`V4_STAGING_ACCEPTED`、`GROWTH_POS=PASS`，实际应用 HTTP 检查通过且旧 8765/8767 仍 active 时报告成功。上述均为 `HOST_NOT_RUN`，Codex 未连接主机。

## 受控回退

若 H 已 active 而验收失败，只回到已核实 c51。若 current 已是 c51（部署器已回切）不再执行 rollback；若既非 H 也非 c51，停止并人工检查。保留失败 f003 目录、数据库、备份与旧服务。

```bash
set -euo pipefail
H=cb06be66e78d92b8921fc3103b12bdbdc55284f8
OLD=c51b58d67dabae53afcdf9851a80cdc93d4200f6
CHECKOUT=/home/ubuntu/bsv-ops-003-verify-next/checkout-$H
CURRENT="$(sudo bsvctl status | python3 -c 'import json,sys; print(json.load(sys.stdin)["deployed_sha"])')"
if [ "$CURRENT" = "$H" ]; then
  sudo /usr/bin/python3 "$CHECKOUT/platform/lighthouse/internal-stage/bsvctl.py" rollback
elif [ "$CURRENT" != "$OLD" ]; then
  echo 'STOP: current SHA is neither H nor the original c51' >&2; exit 1
fi
sudo /usr/bin/python3 "$CHECKOUT/platform/lighthouse/internal-stage/bsvctl.py" verify
test "$(sudo bsvctl status | python3 -c 'import json,sys; print(json.load(sys.stdin)["deployed_sha"])')" = "$OLD"
test "$(systemctl is-active bsv1-preview.service)" = active
test "$(systemctl is-active bsv-all-bsv1-stage.service)" = active
```

## 状态

H 的真实 Python 3.12 venv 构建、`.built` inventory、第二次 build 与 umask 077/022 在 Ubuntu 24.04 CI 通过。三份锁文件 byte-identical；新小型补充包不含 wheelhouse。真实主机状态核验、部署、HTTP、V4 staging 验收和回退演练均未执行。
