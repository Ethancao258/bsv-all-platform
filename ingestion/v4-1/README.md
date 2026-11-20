# V4.1 受控资料接入

**真实资料导入状态 `IMPORT_NOT_RUN`。** 本工具负责在本机预检元数据。真实批次只允许 `review_only`。合成批次可在一次性隔离目录中演练提交、重放、回退及恢复。写入目标仅是导入演练账本。

## 下载模板

| 业务 | 模板 |
|---|---|
| 批次与授权快照 | [批次头](batch-header.template.json)、[授权快照](authority-snapshot.template.json)、[批次 JSON Schema](schemas/batch.schema.json)、[授权快照 JSON Schema](schemas/authority-snapshot.schema.json) |
| 集团法人、直营及合作门店 | [法人 CSV](csv/companies.csv)、[门店 CSV](csv/stores.csv) |
| 已核实人员、旧 POS 码及任职 | [人员 CSV](csv/people.csv)、[旧码 CSV](csv/pos_aliases.csv)、[任职 CSV](csv/engagements.csv) |
| 文森特学院课程、课件、实操及资格 | [课程版本 CSV](csv/courses.csv)、[课件与视频元数据 CSV](csv/media_assets.csv)、[门店资格 CSV](csv/qualifications.csv) |
| 门店排班 | [班次 CSV](csv/shifts.csv) |

保留每个 CSV 的完整表头，无记录时只留表头。课程版本、大小等 CSV 字段在 JSON 中也保留为字符串。集团通用课程在 `store_id` 留空。店级证据引用单独的门店课程版本。日期用带时区的 ISO 8601，若班次跨午夜，应填写两端完整日期。当前资格与排班的职位模板支持 `bartender`。保持既有 TR 与店码，授权范围需已由资料所有者核实。

## 资料准备

1. 在 Git 工作区之外的授权私有目录准备原件、CSV、批次头和只读授权快照。保留实际公司、人员与培训原件在获准的介质。CSV 只填写获准的稳定 IDs 和不带外部链接的证据引用。电话、私邮、合同、证件、视频字节、姓名、薪酬、凭据等不属于模板字段。
2. 由资料负责人核对批次授权、公司与门店范围、处理目的和有效期。授权快照由对接方提供。填写批次的 `source_sha256` 和 `authority_snapshot_sha256` 为两个文件的实际字节哈希。模板里的零值哈希和截止时间是占位。工具按已给出的核准快照比较，不替代审批对证据真实性的核实。
3. 课件元数据只登记私有资源引用、实际文件摘要、权利来源及扫描证据。导入器不打开视频、链接或证据文件，也不会输出“已扫描”。真实上传和使用前仍须实测存储配额、私有读取门禁、文件安全扫描和恢复。
4. 既有法人、门店和 TR 关联必须与授权快照相符。旧 POS 码指向同一 TR 时报告无新增关联，目标 TR 不同则拒绝。冲突输出只含节名、行号、错误码，由人员在受控资料目录核对和修改，不能自动合并人员。

## 前台命令

在仓库根目录执行，将 `PRIVATE` 换为已授权的私有目录。命令行报告只有阶段、计数、错误码，不输出输入业务字段。Python 3.11 或更新版本即可运行。

```bash
PRIVATE=/path/to/authorized/private-import
tool=ingestion/v4-1/import_batch.py
python3 "$tool" assemble --header "$PRIVATE/header.json" \
  --csv-dir "$PRIVATE/csv" --output "$PRIVATE/batch.json"
python3 "$tool" dry-run --batch "$PRIVATE/batch.json" \
  --source "$PRIVATE/source" --snapshot "$PRIVATE/snapshot.json"
```

下列命令仅用于**经过核对的合成资料**，且要求 `mktemp` 创建带专用前缀的私有临时目录。使用 `batch.json` 中实际批次 ID 替换例中的值。

```bash
ledger=$(mktemp -d /tmp/bsv-v41-isolated-import-XXXXXXXX)
python3 "$tool" commit --batch "$PRIVATE/batch.json" --source "$PRIVATE/source" \
  --snapshot "$PRIVATE/snapshot.json" --ledger "$ledger" --confirm-isolated ISOLATED_SYNTHETIC_ONLY
python3 "$tool" restore-check --ledger "$ledger" --confirm-isolated ISOLATED_SYNTHETIC_ONLY
python3 "$tool" rollback --batch-id BSV-IMP-DEMO-001 \
  --ledger "$ledger" --confirm-isolated ISOLATED_SYNTHETIC_ONLY
```

预检报告的 `would_stage` 是当前只读快照比对后的待暂存数。提交的 `write_count` 是实际登记的隔离提案指纹数，另有 `receipt_write_count` 记录批次回执写入。相同批次和来源重放为 0。提交与回退各自是 SQLite 事务，回退保留批次审计记录。恢复演练把账本一致性复制到另一个临时文件，核对完整性和外键后删除演练副本。报告中的 `authority_write_count` 恒为 0。

这个流程仅为资料审核准备，学院发布、资格签发、账号绑定及排班仍须通过各自服务权限和审批。正式导入保留真实数据门禁、私有存储及恢复证明，见[统一导入契约](../../contracts/IMPORT_PROTOCOL.md)。

自动回归命令为 `python3 -m unittest discover -s tests/ingestion -v`。
