# BSV ALL｜ChatGPT × Codex × GitHub × 腾讯云的固定交付工作流（V3）

> **先读**：`AGENTS.md`、`docs/architecture/BSV_ALL_DELIVERY_CONTROL_PLANE_V1.md`、`config/change-routing.json`、`docs/ops/CURRENT_STATE.md`。以上是单一协作协议，不为每位Agent重新发明术语或目录。Issue #9是当前唯一快速集成任务；此前V1/V2提示词是递进修订，不是两轮独立工作。

1. **自然语言需求→机器变更单**：在仓库运行 `python3 scripts/route_change.py "总部人员管理的旧码预检" --scope UI_COPY` 或指定 `--module`。可获模块、源码、测试和命名空间。模糊归属或高风险事项停在 `REVIEW`。ChatGPT/Codex 将正反测试、回退门槛和非目标补入`request_id/module_id/scope/paths/test_positive/test_negative/non_goals/environment/approval`，登记GitHub Issue。需要改多个模块时按文件所有权拆分；未知数据库/权限归属先暂停确认。
2. **Codex代码实施**：固定从GitHub当前PR HEAD读取`AGENTS.md`+注册表+真实状态，不从main或用户对话重新发明工程。修改所属文件、测试、审计/文案映射，提交PR+不可变SHA；只有GitHub已经推送的代码才算正式交付。
3. **CI独立验证**：GitHub托管Actions跑静态路由、业务HTTP、端到端、权限反例、界面及回退模拟；CI绿不是Lighthouse已部署，也不是CloudBase可以迁移。
4. **负责人批准→Lighthouse部署**：`platform/lighthouse/internal-stage/bsvctl.py` 已实现本机手动控制入口，仅支持本次隔离环境。经授权的 GitHub 客户端导出成功 workflow 的 JSON，经营负责人核对链接与完整 SHA 后在主机明确批准。CLI 检查该证据的仓库、SHA、PR 类型、工作流和七项检查，主机保持只读 Git Deploy Key，证据文件由批准者核对和提供。脚本不执行 Issue 文本，也不自动发布。`--verify`或`bsvctl.py verify`仅做健康烟测，另运行`acceptance.py`执行批量授权与业务 HTTP。
5. **数据源变更路径**：`identity.A/B/LOCAL`与`supply.A-G`必须带命名空间。更换物理位置只调整对应已批准服务端运行配置与凭据引用；不允许前端连接数据库，不允许失去权威库时用本地旧快照发权限或写库存。迁移真实CloudBase须G0/G1、官方迁移账本、备份与恢复审批。
6. **实机验收与安全回退**：Lighthouse输出实际部署SHA、业务验收、四类状态PASS/BLOCKED/MOCK_ONLY/NOT_RUN、旧服务结果、出错回退证据；不能把凭据/公网IP/个人信息写入GitHub。更新`docs/ops/CURRENT_STATE.md`。服务端只读Deploy Key无法自动向GitHub写入验收报告；未来建立最小权限的受控回执，不授予服务器通用GitHub写权限。
7. **生产发布单独审批**：新版本公开HTTPS/CloudBase迁移、支付启用、真实员工/顾客资料、主从切换和新增资源费用都需专门许可与可验证回退；当前只允许隔离测试版。
8. **Codex缺失时的诚实边界**：ChatGPT目前可使用GitHub连接器读写Issue/PR/文件，但无法凭这份文档直接触发网页版Codex运行，也没有直接SSH操作腾讯云Lighthouse的授权。用户应在Codex界面启动任务；未来获取所需权限后才能实现“一句话到受控自动发布”。

**每次最终交接**：需求→目标模块→GitHub PR/SHA→CI→批准发布SHA→Lighthouse部署SHA→数据源版本/迁移→主机E2E→回退→风险阻断。始终“先服务人，再维护技术”。


## 版本化证据交接

| 环节 | 所需证据 | 当前执行 |
|---|---|---|
| REQUESTED → ROUTED | 需求编号与模块、来源、路径、正反用例 | `route_change.py` 输出 JSON，人工审核后登记 Issue |
| CODEX_STARTED → PR_READY → CI_PASSED | Issue、PR、完整 SHA 与 CI 运行 | 人工启动 Codex，GitHub 托管 CI |
| REVIEW_APPROVED → RELEASE_APPROVED | 批准者、完整 SHA 及对应 CI 导出 | 人工核对并显式批准 |
| DEPLOYING → HOST_VERIFIED | 本机 SHA、预检、备份和回切点 | `bsvctl.py deploy` 写本机发布记录 |
| STAGING_ACCEPTED / STAGING_BLOCKED | 本机版本、逐项 HTTP 证据、阻断原因 | `acceptance.py` 写关联验收报告 |
| ROLLED_BACK | 恢复版本、服务健康与原因 | `bsvctl.py rollback` 前台执行，保留数据 |
