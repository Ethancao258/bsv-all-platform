# BSV ALL｜CloudBase → Lighthouse 每日产品数据同步（第一批）

基线：已在 Lighthouse 隔离运行的 G1 SHA \`f6d8ce9b9c027baeaa0bdd5b62457fea40adeb27\`。

## 已实现（本 PR）
- 独立、只读的 CloudBase PostgreSQL HTTPS 拉取器：\`integrations/cloudbase/catalog_daily_pull.py\`。
- 针对现有 8 张产品/报价/门店/菜单表，只执行 \`GET\`；不包括导入审计表、身份、顾客、订单。
- 每表一页上限 1000 行；响应总数不一致、超过上限、权限失败或字段不符则整体失败，**绝不静默遗漏**。
- 候选包原子落盘，0700 私有目录 / 0600 文件，保存行数和 SHA-256，**不修改 CloudBase，不修改当前 POS SQLite，不切换线上商品**。
- 测试：\`python3 -m unittest discover -s tests/cloudbase -v\`（纯离线，不用真实令牌）。

## 目标架构（经用户确认）
1. 由总部授权人员在 **上海 CloudBase PG** 维护产品、配方、套餐和各门店有效报价；
2. 每天按 **北京时间 04:30** 在 **北京 Lighthouse** 发起一次 HTTPS 拉取；CloudBase 每天仅承受一轮产品快照读取，不承受门店每笔点单流量；
3. 验证完整性与「已审核 / 已发布 / 可售 / 价格生效期」后，才切换 **Lighthouse 本地的已发布产品只读投影**；
4. 三店 POS 从本地投影读取商品，订单仍保留在其独立事务存储；历史订单价格/名称/配方版本不可被后续发布改写；
5. CloudBase 网络不可用时继续读取最后一次 **有效且未被安全撤销** 的本地已发布商品版本；不得用过期库存/身份/支付事实作回退。

## 当前尚未完成（不得宣称可经营）
- CloudBase 实库 schema、RLS、数据权限、套餐/价格/发布版字段语义的实时核验；
- 服务端 **最小 SELECT 权限**的持久凭证（切勿将 service_role / 管理员 API Key 放入门店或提交 Git）；
- 从候选包到 POS 可读投影的转换及人工审核/正式发布门禁；
- systemd service/timer **模板已提交但未安装或启用**；连续两天失败告警及密钥轮换尚未实现；
- 门店级有效价格校验、紧急停售的手动即时发布、真实 POS 价目及配方验收；
- CloudBase Excel 导入在当前 PG 环境的具体方式和差异预览。

截图中的 \`bsv_bundles\` 有 \`approval_status=unreviewed\`、\`is_visible=false\`，**此类商品必须保持不可售**。不能将 \`reference_price\` 当作门店有效收银价。

## 定时模板（当前不可启用）

- `platform/lighthouse/catalog-sync/bsv-all-catalog-candidate.service`、`.timer` 已作为**禁用模板**提交；计划每日北京时间 04:30 启动。
- 必须先核验凭据的只读权限及有效期、实际 RLS/GRANT、日志告警、服务权限与主机资源，再通过单独批准的运维变更安装并启用。
- 日更的是 *candidate* 快照；不会把未经审核的商品自动发布到 POS。

## 只读示例（只在隔离运维端手动运行，勿在公开页面执行）
\`\`\`bash
# 先通过 CloudBase 官方权限管理准备服务端专用、最小只读身份。
# 使用受限环境文件由运维注入以下两个变量；不要粘贴实际值到命令行或日志。
# BSV_CLOUDBASE_ENV_ID=...
# BSV_CLOUDBASE_READ_TOKEN=...
umask 077
python3 integrations/cloudbase/catalog_daily_pull.py \
  --output-root /var/lib/bsv-all-catalog-sync/candidates
\`\`\`

输出 \`CANDIDATE_NOT_APPROVED_NOT_PUBLISHED\` 才是当前阶段的正常结果。**禁止把本脚本生成的候选包直接改名为 \`current\`，也禁止覆盖 \`/var/lib/bsv-all-internal-stage/pos/synthetic.sqlite3\` 或 \`synthetic-v9.xlsx\`。**

## 后续验收门槛
1. 从实际 CloudBase 权限受限身份成功读取8张表，行数和哈希可重复核对；
2. 根据真实 schema 建立 \`published_catalog.v1\` 转换，未审核/无有效门店售价/停售/缺配方一律不可售；
3. 本地发布切换采用两阶段验证+原子指针更新+保留上一有效版本；
4. 三店 POS 用真实快照做开桌、查酒、下单、出品、断网、紧急停售、回退验证；
5. 每日定时一次 + 失败告警 + 一次人工强制同步，运行日志不包含敏感密钥；
6. 所有写入均只落在 Lighthouse 的受控候选/投影位置；CloudBase 同步账户为只读。

**当前绝不执行 CloudBase DDL、写入、删除、Lighthouse 正式切库或公开支付。**
