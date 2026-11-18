# 以后增加功能，决策顺序固定

1. 查 V5 组织母版，判断需求属于 BSV1、BSV2 或 BSV3（有些动作可跨圈层，但必须指定主责）。
2. 查 `config/domain-registry.json`，找到业务事实 owner；找不到先向注册表提出新增 domain / entity 的变更，不允许同名影子表。
3. 查 `config/app-registry.json`，选择哪类员工/用户使用界面；如新端只在 `apps/` 下新增二级目录。
4. 查 `contracts/`，设计稳定业务动作API/事件、权限范围、有效期与异常状态。先定义错误回退，再做网页。
5. 写迁移草案与数据导入映射；真实云端先只读盘点、备份恢复演练；Codex仅能在授权范围执行。
6. 改动走分支 → 测试 → PR → 经授权发布 → 真环境检查 → 更新 `CURRENT_STATE.md`。禁止凭AI记忆跳过。
7. 若确实出现一级目录无法容纳的全新类型，必须提交解释为什么14个根目录都无法承载的 ADR；默认拒绝重命名既有一级目录。

**判例**：新增线上下单，只在 `apps/guest-web` 加功能，订单仍写 `domains/commerce`；新增中央配送只扩 `capabilities/bsv2/central_supply`，批次继续用 `domains/production`，不再造一个 `bsv2_batches` 主库。
