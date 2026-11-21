# BSV-OPS-002 · GitHub 与腾讯云只读交付桥

## 本轮交付边界

当前实现是 **M1 MOCK_ONLY**：可在本机和 GitHub Actions 内执行签名任务、固定操作模拟、产物摘要核验、防重账本和脱敏结果回环。它不创建 TAT/COS SDK 客户端，不连接腾讯云，不访问 Lighthouse，不安装或调用服务器命令。`READ_DIAGNOSE` 和 `VERIFY_ARTIFACT` 的本地闭环不能被解释为云端诊断成功。

真实 TAT/COS 通道和 `STAGING_DEPLOY` 均关闭。生产、数据库迁移、真实收款、公网开放、任意 shell 和由 Issue 文本派发命令均被策略拒绝。Issue #31 的后续云端阶段需要单独的一次性授权；在收到授权前停止于本地模拟。

## 工程归属

架构锁定的 14 个顶层目录不允许新增 `ops/` 根目录，因此文件按现有所有权放置：

- `contracts/ops-bridge/`：带版本的任务与结果 JSON Schema。
- `platform/ops-bridge/`：策略、协议、执行器、本地防重账本及隔离的 TAT/COS/GitHub 适配协议。
- `tests/ops-bridge/`：仅用合成输入的安全和闭环测试。
- `.github/workflows/validate.yml`：新增最小权限 M1 CI 门禁。
- `.github/workflows/bsv-ops-bridge-dry-run.yml`：手动触发的本地 mock 工作流；不取云凭据。

## 协议与安全状态机

任务固定仓库名、请求编号、操作、环境、完整目标 SHA、精确匹配的 CI run id/URL/head SHA、短有效期、随机 nonce 与 HMAC-SHA256 签名。Schema 不允许未知字段；操作策略拒绝生产与部署。执行器先验签和过期检查，再原子占用 task id + nonce；同一任务只能消费一次。暂时性错误最多重试两次，其他失败立即结束。最终结果绑定 task id、请求、操作、环境和目标 SHA，并由 HMAC 验证。

身份密钥从环境变量读取时必须是完整的临时 STS 凭据组；对象 `repr` 不暴露密钥。当前 GitHub workflow 不提供或读取任何 Tencent 凭据。SQLite journal 仅保存运行任务状态，不保存业务数据；目录和文件须当前用户拥有，权限为私有，拒绝符号链接。GitHub 兼容报告使用固定字段，隐藏凭据、邮箱、IP 和绝对路径；原始日志从不进入报告。Mock fixture 中的日志会被丢弃。

未来 TAT 只允许指定实例与预先登记、校验摘要的固定命令 ID。任务只携带受限元数据，不携带 shell 文本、命令路径、凭据或 Issue 原文；固定 runner 还必须核对 `expected_command_sha256`，并拒绝非 allowlist 的实例、环境或操作。COS 对象路径固定于 `bsv-ops-bridge/` 私有前缀，写入要求私有 ACL、AES256 加密且禁止覆盖；下载的构件需同时匹配目标 SHA 前缀、长度和 SHA-256。云适配器目前只定义注入式接口和闭合传输组合，真实腾讯 SDK 请求尚未实现或验证。

## 一次性云端授权前置条件（M2，当前未执行）

需要经营负责人在腾讯云控制台批准一个仅供隔离环境的授权窗口，并核准：

1. 专用临时 STS 凭据或同等可撤销的工作负载身份；仅允许目标 Lighthouse 实例上的指定 TAT 固定命令和私有 COS 桶内 `bsv-ops-bridge/` 前缀读写。不得授予 Lighthouse 登录、任意命令、生产实例、数据库、支付或公网配置权限。
2. TAT 命令源码与摘要审核；首阶段只包含读取服务状态/版本和受限健康检查，明确禁止 shell 参数注入与日志秘密读取。
3. COS 桶保持私有、开启服务端加密、拒绝覆盖，设置短期生命周期；原始诊断日志留在受控 COS，公开 GitHub 只接收脱敏的小型结构化状态。
4. 独立、可撤销的 GitHub 回写身份或受控回写接收器；目前没有配置 GitHub App/Checks 写权限，M1 只在 workflow 输出模拟结果。

必须在仓库外安全配置临时凭据，不能粘贴到对话或提交仓库。批准窗口结束后立即撤销并记录回执。M2 仅可完成 `READ_DIAGNOSE`/`VERIFY_ARTIFACT` 隔离验证；启用 staging 发布必须另行审批并接入经过审查的版本化 `bsvctl`、健康验收和代码回切。不得在此任务中接入生产。

## 复现命令

```bash
python3 -m unittest discover -s tests/ops-bridge -v
python3 platform/ops-bridge/runner/cli.py --mock-roundtrip --operation READ_DIAGNOSE --sha "$(git rev-parse HEAD)"
python3 platform/ops-bridge/runner/cli.py --mock-roundtrip --operation VERIFY_ARTIFACT --sha "$(git rev-parse HEAD)"
```

以上命令只运行合成模拟。预期结果中 `host_contacted=false`。真实云端授权和主机验收状态为 `NOT_RUN`。
