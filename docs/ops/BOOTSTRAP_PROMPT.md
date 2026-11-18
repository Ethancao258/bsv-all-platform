# 给 Codex 的首轮指令（精简、可执行）

你负责 BSV ALL 全集团云端工程。使用我提供的 **V2.0 锁定基线**作为唯一新工程目录；先读 `AGENTS.md`、`README.md`、`docs/governance/BSV-GOV-ARCH-2026-005_V5.0_20261118.md`、`config/` 注册表和 `docs/ops/CURRENT_STATE.md`。

**本轮目标：新建独立私有 GitHub 仓库 + 验证架构 + 云端只读盘点；不修改生产数据。**

1. 验证 GitHub 登录和 `Ethancao258/bsv-all-platform` 是否已存在：不存在则创建私有 `main` 仓库；存在则先核对差异，禁止覆盖。不碰旧仓库。
2. 将当前V2.0目录原样提交推送，执行 `python3 scripts/verify_architecture.py`，记录 commit SHA。
3. 通过已授权 CloudBase MCP 只读查询 `inadequate-marten-d1dn9lb5fce2c0` 的 PG schema、现有10张产品业务表、`bsv_stores`/门店身份主数据、迁移历史和备份恢复能力；禁止DDL和数据写入。
4. 如果已授权 Lighthouse SSH/TAT，只读盘点 `/srv/bsv`、BSV1代码路径、服务、端口与备份；核对 EdgeOne Makers `menu.bsvm.cn` 实际站点与部署关联。没有权限就注明未核实，不要猜。
5. 依据真实证据更新 `docs/ops/CURRENT_STATE.md`、`config/resource-registry.json`，仅写无密钥、无个人隐私的结果，提交 Git。
6. 输出：仓库URL、commit SHA、静态校验结果、已核实云资源、冲突表/路径、恢复备份状态，以及下一轮“数据库基础迁移方案”的前置条件。

**注意：BSV1/2/3为经营圈层，BSV ALL是唯一共享数据底座；固定14个根目录。** 当前未授权生产迁移、收银替换、付款接入、网站上线或新增付费资源。除GitHub私有仓库创建外不执行写操作；不要基于候选SQL预建几十张空表。
