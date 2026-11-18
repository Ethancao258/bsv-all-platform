# 大规模原始数据与旧系统接入（Git只存规范）

- `templates/`：导入批次结构、必需审计字段与脱敏样例。
- `mappings/`：原Excel/本地SQLite/菜单版本/供货表到唯一数据域字段的显式映射。
- `pipelines/`：分析、校验、幂等导入流程代码（按实际需要实现）。
- `quarantine/`：只可存失败原因和脱敏统计，不能放未经授权的个人原件。

**不可逆规则**：源文件在经授权的私有存储中保存不可变字节，仓库只提交不可泄露的索引与映射。原数据每批先 dry-run 和比对，再人工批准发布。

本轮资料清单见 `mappings/source-index.json`。清单覆盖三个用户附件，基线 ZIP 内部目录由 Git 树与原始文件清单追溯。真实原件继续留在受控来源。

### 批次预检

`python3 ingestion/pipelines/validate_import.py SOURCE MAPPING APPROVED_SNAPSHOT`

- `MAPPING` 包含 `source_sha256` 和 `identities`。每项为 `key`、原来源的 `external_key`、已存在的 `canonical_id`。映射须覆盖该批涉及的产品、门店、员工和物料引用，由针对来源的解析器产出并经人工核对。
- `APPROVED_SNAPSHOT` 由获授权的只读工具取得，包含 `imported_source_sha256` 和 `identity_mappings`，后者按数据域、ID 字段、来源键映射至权威 ID。快照留在受控位置。
- 预检仅验证源文件哈希、已导入 SHA 和权威 ID 映射。正式执行器获准接入后，须在同一事务中对官方导入账本实施 SHA 唯一性及映射复核，防止并发重复导入。
