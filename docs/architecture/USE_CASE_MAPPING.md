# 原始需求如何固定到工程目录

`config/use-case-registry.json` 是唯一机器可读关联表。每条记录包含：`id`、`capability_id`（经营主责）、`domain_ids`（业务事实来源）、`app_id`（界面入口）、`action`（目标动作）、`fallback`（增强中断后如何处理）和 `status`（证据状态）。

**例如**：员工考完考试自动拥有基础出品资格，属于 `bsv1.learning.exams` → `capabilities/bsv1/people` → `domains/learning + identity_access` → `apps/staff-center`，最终门店 `apps/store-console` 每次调用受控API重新判定资格有效性。不会把考试成绩存进收银数据库。

**例如**：中央供应 `bsv2.supply.central` 与门店自制 `bsv1.store.local_procure` 使用同一个物料与库存身份；中央配送的批次与签收由 `production` 域持有，不另造「BSV2产品主库」。

**例如**：BSV3资本预算从经营财务读取已核实现金流，但是不能直接操作门店原始支付事件；资本投资使用 `capital` 域独立审批。

**如果新增功能**：注册一条用例，查已有能力与域，没有时优先创建现有目录下二级模块；增加新唯一实体要在 `data-ownership.json` 明确归属并通过检查。不要把每个使用者页面当作另一个服务或数据库。
