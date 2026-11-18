# 跨 AI、跨周期统一工作机制

1. **决策**：ChatGPT/人工确定业务归属与验收指标；文件进入 Git (`docs/decisions/ADR-*.md`)；口头会话不能代替架构记录。
2. **实施**：Codex 阅读 `AGENTS.md` + 注册表 + `CURRENT_STATE`；在同仓库分支做功能、迁移草案、测试，记录工具证据。
3. **数据**：WorkBuddy仅负责授权范围内的文件整理和映射提案，**不能凭文档理解直接写CloudBase正式表**；所有导入受同一 `ingestion` 规则控制。
4. **部署**：Codex以MCP操作CloudBase；Lighthouse需额外授权 SSH/TAT；EdgeOne需核对项目及部署权限。生产写入由人批准且先恢复测试。
5. **复核**：ChatGPT从GitHub读取代码、PR、测试与 `CURRENT_STATE`；不能自动读取Codex未推送本地对话，也不能仅凭Git文档推断服务器真实状态。
6. **归档**：每轮记录ADR、提交SHA、数据库迁移号、发布版本与回退计划；架构扩展优先新增二级目录，不改根名。
