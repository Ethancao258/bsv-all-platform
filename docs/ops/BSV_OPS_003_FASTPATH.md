# BSV-OPS-003 · f003 快速可信交付

## 范围与目标

首个待见版本固定为 `f00371ccd1c233caf8eea97398bf981cf7d65dd0`，不是当前正在开发的 PR SHA。V1 在 GitHub 托管 runner 上取该提交的 Git tree，核对 PR #27 的已成功运行 `44894443077` 与九项门禁，生成只读源码包、可离线 clone 的精确 Git bundle、文件级 Git blob 清单和 `bsvctl` 可读 CI 证据；GitHub OIDC keyless Cosign 对整个包签名，GitHub Artifact Attestation 再记录构建来源。构件 SHA256、签名 bundle 和 CI 证据随短期 Actions artifact 保存。包不含运行时 `.git` 工作目录、真实数据或凭据；`source.gitbundle` 只带精确目标及其 Git 对象历史。

OIDC 联合角色使用腾讯云官方 `AssumeRoleWithWebIdentity` 临时 STS 流程；COS 客户端仅采用官方支持的临时密钥三元组。参考：[腾讯云 OIDC 角色临时凭证](https://cloud.tencent.com/document/product/1312/73070)、[腾讯云 COS Python SDK 上传对象](https://cloud.tencent.com/document/product/436/65820)。

该通道不使用 Lighthouse 到 GitHub 的网络访问，也不要求负责人下载后再上传源码文件。COS 发布器和 GitHub Actions 上传 job 已实现，但默认关闭：必须负责人配置受限 Tencent OIDC 角色、私有 COS bucket/region/provider 参数，并显式将仓库变量 `BSV_OPS003_COS_UPLOAD_ENABLED=true`，之后手动运行 workflow 并选中 `publish_to_cos=true` 才可能上传。本轮没有启用该变量、触发上传或联系 COS/TAT/服务器。V2 主机发布仍需要独立的 TAT runner 授权与实机验收。

## 构件验证

GitHub workflow 名称为 `bsv-ops-003-release`。PR CI 会从 GitHub Actions 下载构件；首次授权后，固定 SHA 可通过 `workflow_dispatch` 重新生成。预期文件：

- `bsv-all-f00371ccd1c233caf8eea97398bf981cf7d65dd0.tar`（内含 `source.gitbundle`、manifest、CI 证明；可在本地无网络 clone 精确 SHA）
- `.tar.sha256` SHA256 文件
- `.tar.sigstore.json` keyless 签名材料
- GitHub Actions build provenance attestation

先用 Sigstore 根证书验证签名，再运行当前源码中的 `ops003_release.py verify`。PR 工作流签名身份限定本仓库该 workflow 的 PR merge ref 或指定工作分支；合并到 main 后的手动运行身份限定 main。issuer 固定为 GitHub Actions OIDC。离线文件内容验证会重新检查 outer checksum、精确 manifest、PR #27 CI URL/head SHA/九项成功作业、gzip archive 摘要、所有 Git blob SHA/mode，以及 `source.gitbundle` 克隆后的 commit/tree 身份。验签必须先于包内任何工具执行。

`source.gitbundle` 保留目标 Git commit 和对象，因此后续固定 TAT runner 可以在主机本地 clone，再由现有 `bsvctl.py` 核对目标 SHA 和包内 CI 证明；不需要主机到 GitHub 取源码。该 runner/COS 上传仍须 V2 前的 Tencent 授权和一次性主机验收。

本地复核（开发分支需有 f003 Git 对象与可读取的 GitHub CI run）：

```bash
python3 tests/internal-stage/test_ops003_release.py
python3 platform/lighthouse/internal-stage/ops003_release.py build \
  --run-json /path/to/verified-github-run.json --output /tmp/bsv-ops003-release
python3 platform/lighthouse/internal-stage/ops003_release.py verify \
  --bundle /tmp/bsv-ops003-release/bsv-all-f00371ccd1c233caf8eea97398bf981cf7d65dd0.tar \
  --sha256 /tmp/bsv-ops003-release/bsv-all-f00371ccd1c233caf8eea97398bf981cf7d65dd0.tar.sha256
```

本地 `build` 只接收 task 内固定的 #27 CI run，不能改目标 SHA 或 CI URL。包大小受 100 MiB 限制；输出路径为私有目录，已存在输出拒绝覆盖。

## 三道门禁状态

1. **V1｜GitHub 构件**：源码、签名、摘要和既有 CI 证据由本 PR 实现并由当前 GitHub Actions 验证。没有腾讯云访问。
2. **V2｜隔离主机**：BLOCKED，等待负责人批准一次性最小权限 Tencent OIDC 角色。仅允许指定 COS 私有前缀和单个 Lighthouse 实例上的固定 TAT command；不得 SSH 登录、任意 shell、生产实例、数据库、支付或公网改动。实际发布必须用既有 `bsvctl`，先核实主机版本/回退/互斥锁/磁盘和加密备份，再由负责人确认，随后检查健康与批量验收，失败则用既有安全回退。Cloud role/OIDC provider/instance/command/COS bucket 尚未核实，均 UNKNOWN。
3. **V3｜网页可见**：BLOCKED，V2 主机验收后，确认当前 SSH 隧道确切的本地与远端端口，将新的本地独立端口转发到 `127.0.0.1:18760`；绝不改旧 8765/8767。负责人在同一隧道 origin 检查工作台、POS、HQ、学院、会员、增长和鸡尾酒页，并由真实浏览器截图确认版本。

“GitHub artifact 已构建”不等于“COS 已传送”“主机已部署”或“网页已可见”。当前最后已验证主机版本仍以 `CURRENT_STATE.md` 内经营者提供的证据为准，未再次查询。

## 唯一前置授权

无长期静态密钥。下一步需要经营负责人一次性批准并配置 GitHub Actions OIDC 联合身份的最小资源范围：固定私有 COS bucket 的 `bsv-ops-003/f00371.../` 前缀写入、固定隔离 Lighthouse 实例上的已审核 TAT command；不能授予任意 TAT shell、其他实例、数据库或公网配置权限。角色会话需短时、可撤销并留审计回执。配置完成后由仓库侧手动触发 COS 上传，不需要负责人再次上传源码包；真正主机部署仍必须经过预检和单独确认。
