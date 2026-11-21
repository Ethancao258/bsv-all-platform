# BSV ALL V4.3｜会员 × POS 联调交付与真实主机门禁

**状态：CODE_DRAFT｜PR #27（基于已过CI的PR #26）｜CI_NOT_VERIFIED_AT_NEW_SHA｜HOST_NOT_RUN｜PRODUCTION_NO_GO。**

本文件供实际服务器执行者读取，不授权绕过主机、数据库、财务或公网安全约束。源文件在 `feature/v4-3-pos-growth-closeout`，最终发布必须在PR自身九项 `pull_request` CI于同一SHA全部成功后重新定版。

## 现在已开发的代码（不等于生产验证）

- 客户 `/member/` 仅在隔离环境可用**虚构身份**登录、注册并生成一次性、门店限定、120秒HMAC签名授权码；不从二维码/纸卡推断真实到店。
- 原POS `/pos` 在已核验当前店、员工TR、设备、学员资格和确认班次后核验一次性授权码，要求当前OPEN的visit，记录**唯一** `canonical_customer_id` 引用到现有 `visit_member_links`。老 `members` 表没有被复制，新会员不会误触银卡折扣。
- 绑定原子消费nonce。相同 `_action_id`、相同授权码/店/桌次的网络重试返回原成功结果；更换操作号重放拒绝，避免重复绑定。
- POS服务端对当次visit发放90秒HMAC读令牌，会员服务再以**内部受信URL**请求POS核验该浏览器当前会话、TR、设备、有效班次、店、访问的visit和会员关联，拒绝跨店、无授权、已离店、撤销设备。
- 客户随时撤销调酒师查看风味的授权；查询服务实时读取customer-owned candidate preferences，不能缓存未授权数据。POS有权接待与营销人员认领是两种不同权限。
- `bsvctl.py` 发布证据严格要求九项CI（包括 `customer-growth-v43`）；`config/change-routing.json` 已登记 `customer-growth` 模块。
- 三种密钥（客户授权、POS短期接待token、内部核验）分别持久保存在主机root 0600私有文件。运行于既有127.0.0.1:18760/18762，**不新增公网服务**。旧服务8765/8767保持原样。
- 隔离客户候选SQLite快照已纳入 stage backup；POS投影为只在隔离受管路径应用的可兼容增量迁移。

## 关键限制

客户候选库不是已验收的集团Customer权威主档；正式CloudBase schema、RLS、真实员工组织/法人/全五店映射、微信公众平台授权、隐私告知、支付回调验签及对账、客户权益正式核销、佣金政策和工资结算**仍未具备生产验收凭证**。不能用内部调试注册或模拟付款当作营业。

## 当前CI基础设施阻断

2026-11-21 GitHub Actions新分支相关运行出现**全作业瞬时failure、无runner_name、无steps、无可用job log**；这是没有实际执行测试代码的失败记录，不能据此判定代码PASS或FAIL，具体GitHub账户/Runner原因仍待查。原PR26的9/9成功仅适用于 `d365717d1e65b95073b3d72b5ce521d3bb92a604`，绝不可借其验证当前PR #27。

先由仓库所有者检查 GitHub Actions 对应失败运行页面的检查注释、账单/配额及可用Runner设置，修复后**重新触发PR #27准确HEAD的全部九项检查**。在此之前禁止隔离自动发布。

## 限定Codex职责｜仅真实环境操作

1. **只读取证**：用户在 `/home/ubuntu` 运行 `python3 platform/lighthouse/internal-stage/bsvctl.py status` 报文件不存在，是相对路径错误；先只读列出 `pwd`、`ls -ld /opt/bsv-all-internal-stage /opt/bsv-all-internal-stage/current`、按受限路径定位真实工作树及 `bsvctl.py`，读取 `git status` 和 `git rev-parse HEAD`、systemd端口/资源和已有备份；不可假设仓库在 `~`。
2. **CI+授权**：只有九项完整GitHub PR CI已`completed/success`、SHA与洁净工作树和运营方批准对应，才从现有官方发布控制器 `bsvctl.py` 完成 `ci-evidence` 导出、只读`status`、`deploy --approve-isolated --module customer-growth --module store-pos --module deployment-config` 和 `verify`。保留原 `identity-api`等相关模块批准范围，不允许绕开已有部署校验。
3. **真实HTTP隔离验收**：运行 `acceptance_v41.py` 新增的 `GROWTH_POS`合成路径，证明顾客授权、正确门店绑定、重复请求、员工在班/设备、撤权、隐私撤销、旧POS路径均通过。再进行快照、受控恢复检查和回滚可行性检验。**不要触碰真实客户身份、微信密钥或任何收款。**
4. **回传证据**：实际服务器部署SHA、端口、匿名拒绝结果、GROWTH_POS的PASS/BLOCKED结果、checkpoint/备份与回退状态。不得上传真实客户信息、环境密钥、完整会话或PII。

验收入口（仅隔离发布成功后经SSH隧道访问）：`http://127.0.0.1:18760/`、`/member/`、`/staff/growth/`、`/pos`、`/staff`及`/hq`。当前**不能保证上述URL已在主机部署或可访问**。

## 完成定义

- `CODE_COMPLETE`：真实源码+缺口接口+受限运维工具齐全；
- `CI_VERIFIED`：当前SHA九项GitHub CI通过，且新增真实PG17 + POS device + guest跨模块验收测试实际执行；
- `HOST_VERIFIED`：Lighthouse 真实部署、可经SSH访问、回退和备份证据；
- `PRODUCTION_READY`：官方主库、真实人员门店、支付、隐私/监管和结算独立验收全部通过。

不要把任何阶段等同于后一阶段。