# BSV ALL 工程真实状态

**盘点时间** 2026-11-18T13:09:24+08:00
**执行者** Codex
**V2.0 原样导入提交** `9d03b6eafe1f9c23e16a4b6b689d882a07369c20`
**GitHub 目标** https://github.com/Ethancao258/bsv-all-platform
**发布状态** 私有仓库 `main` 已发布。本文所在提交可通过 `git log -1 --format=%H -- docs/ops/CURRENT_STATE.md` 查询。

| 资源 | 证据与状态 |
|---|---|
| V2.0 锁定基线 | ZIP 中 106 个文件与原样导入提交逐字节一致。运行 `python3 scripts/verify_architecture.py` 通过：14 个一级目录、17 项经营职能、20 个数据领域、32 项功能映射、6 个界面入口、65 个 ID 唯一归属；组织 V5.0 原文 SHA-256 校验通过。独立上传的用例注册表与 ZIP 内版本逐字节一致。 |
| GitHub 私有主仓库 | 已认证为 `Ethancao258`。目标仓库查询 HTTP 404，当前授权下不可见。GraphQL 创建返回 `Resource not accessible by integration`，REST 创建 HTTP 403。未获得仓库存在、私有属性或远端分支证据。旧仓库 `bsv`（`master`）及 `BsvAll-BarOps`（`main`）仅查询了元数据。 |
| CloudBase PostgreSQL | 注册表报告 `ap-shanghai`、环境 `inadequate-marten-d1dn9lb5fce2c0`、PG 17.11 和 10 张产品表。远程 MCP 初始化 HTTP 401；本地 MCP 2.37.7 的 `auth(status)` 返回 `REQUIRED`，无已绑定环境。`queryPgDatabase(context)` 返回 `AUTH_REQUIRED`，`managePgDatabase(listMigrations)` 因未登录失败。实例、schema、10 张表的名称及约束、`bsv_stores`、RLS/GRANT、迁移版本和备份恢复条件均未核实。 |
| Lighthouse 北京 | 注册表报告 Ubuntu 24.04、4 核 4 GB、40 GB 磁盘，登记了 `/srv/bsv/{core,stores,public,services,data,incoming,ops}` 目录约定。本环境没有可用的已授权 SSH/TAT。实例 ID、运行服务、工作目录、端口、BSV1 路径、部署版本和备份均未核实。 |
| EdgeOne Makers 菜单 | 已报告域名 `menu.bsvm.cn`，路径 `/cocktail/`、`/craft/`。本环境缺少已授权的 EdgeOne 项目查询工具。公开 HTTPS 检查在代理 CONNECT 阶段返回 403，未收到站点响应。Makers 项目 ID、域名绑定、生产部署及实际发布位置均未核实。 |

## 第二轮接入与校验

**核查时间** 2026-11-18T13:17:40+08:00

- 校验器独立提交 `fee81eac7f06efb6c53a1764dc3e18bf1a4f0d31` 仅更新校验脚本及其文件清单哈希和字节数。现有工作区与含普通 `.git/` 的临时检验环境均通过，添加额外业务目录时仍会正确失败。GitHub Actions 结果为 UNKNOWN，详见下方 GitHub 主仓库发布记录。
- GitHub CLI 官方设备登录及 `repo,workflow` 权限刷新均已完成，身份为 `Ethancao258`，但 `gh auth status` 仍显示无权限范围。个人 CLI 身份查询目标返回 HTTP 404，建库返回 `Resource not accessible by integration`。远端仓库存在性、私有属性和 `main` 均为 UNKNOWN。
- CloudBase 国内站的官方 MCP OAuth 已启动并交接浏览器登录。OAuth 结果和目标环境绑定状态为 UNKNOWN。数据库版本、产品表、主键、约束、RLS、迁移记录及备份恢复能力均为 UNKNOWN。
- Lighthouse 和 EdgeOne 延至下一阶段核查。

## 下一轮数据库底座阻断项

1. G0：为 CloudBase MCP 接通目标环境的只读授权。核实 PG 实例与 schema、产品表结构和约束、门店 ID 权威来源、RLS/GRANT 及官方迁移历史。现阶段无法判断同名表或 ID 冲突。
2. G1：核实有效备份、保留期、恢复权限、恢复目标及恢复点。取得隔离环境恢复演练、结构与数据校验的证据后，再进入候选迁移的设计与预览。
3. 在确认运行依赖前，补查 Lighthouse 服务与 BSV1 部署目录、EdgeOne 发布绑定。主库位置与跨区 TLS、延迟、故障回退等决策沿用现有 ADR 的待验证状态。
4. 取得目标私有仓库的建库和推送权限。目标已存在时先比较分支和文件差异。以该仓库及其 `config/` 注册表作为后续工作唯一事实源，继续保持 14 个一级目录和唯一主数据归属。

本轮生产变更和数据库迁移版本均为无。备份恢复能力未知。本地状态记录可以单独回退，原样导入提交保留为 V2.0 基线。

## 第三轮 · GitHub 与资料索引

- GitHub 集成及个人 CLI 均查询目标仓库返回 HTTP 404。建库和推送沿用现有本地历史，等待确认私有仓库及访问授权。GitHub Actions 及跨工具仓库访问均为 UNKNOWN。
- 扫描了用户附件、资料区及现有工程。排除工具缓存、授权文件和本地构建副本。可用来源共 3 个：1 个 V2.0 ZIP、1 份 Markdown 引导、1 份 JSON 用例注册表。ZIP 内 106 个文件已在原始提交归档，后两份与已归档文件逐字节一致。未发现新增的 SOP、配方、菜单、教学原件、标签规范或旧 BSV1 程序。安全原因排除的业务来源为 0。
- `ingestion/mappings/source-index.json` 记录来源与 SHA-256。`ingestion/pipelines/validate_import.py` 可对已审核的映射及权威只读快照做预检。实际批次、正式导入与生产数据库变更均为无。

## 第三轮 · 合成数据预览

- 用户确认目标 GitHub 仓库尚未创建。个人 CLI 重试创建私有仓库返回 HTTP 403，远端 SHA、Actions 与 ChatGPT 跨工具读取仍为 UNKNOWN。
- 本地菜单预览、BSV1 点单草稿演练和 `GET /api/v1/menu` 已实现。HTTP 检查通过，菜单网页和 API 使用同一合成快照。运行 `python3 services/api/preview.py` 后，菜单位于 `http://127.0.0.1:8765/`，门店演练位于 `/store/`。原版 BSV1 程序未提供。
- 导入预检已用合成数据核验正常映射、拒绝已导入 SHA、拒绝 ID 冲突及哈希不符。未执行正式导入。
- EdgeOne 预览候选目录是 `apps/guest-web/preview`。GitHub 及 EdgeOne 项目访问尚未打通，云端预览 URL 为 UNKNOWN。Lighthouse 未部署。生产菜单、收款、员工认证和会员服务未变更。
- CloudBase G0 仍待已授权会话，包括实际版本、表、主键及约束、RLS、迁移和备份恢复能力。数据库迁移版本为无。发布前可分别回退本轮资料索引与预览提交。


## GitHub 主仓库发布

**核查时间** 2026-11-18T13:34:52+08:00

- 通过 GitHub API 和 Git 引用查询确认目标是私有空仓库。现有本地 `main` 通过普通推送建立远程 `main`，完整保留本地提交历史。首次推送后，远程 SHA 与本地 `98432c112c4ec86c1a454459eeb257a33709fe5a` 一致。
- 本地架构校验通过。GitHub Actions 的 `validate-architecture` 对首次推送运行成功。[运行记录](https://github.com/Ethancao258/bsv-all-platform/actions/runs/44245183954)
- 后续以该私有仓库的 `main` 与现有业务注册表为工程版本来源。GitHub CLI 已验证可访问。其他客户端的读取状态取决于各自授权。

## BSV1 V3.1 交接集成

**日期** 2026-11-18（北京时间）。回退基线 `e2a0368bb89d30627c5eae9be062cae38f82760d`，集成提交见分支 `integration/bsv1-handoff`。

- 交接 ZIP CRC、原包清单和 V5.0 治理文件哈希均通过。63 个原件及来源与目标映射记录在 `ingestion/sources/bsv1-final-20261118.json`。原始 V9 工作簿及原始平面图留在交接来源，Git 保留三店候选 JSON/SVG 和品牌标识。包内 V9 哈希与交接声明相符，CloudBase 权威库存版本未核实。
- POS、调酒任务、HQ 地图与受控菜单已从交接源码集成。详细映射见 `config/modules/bsv1-handoff.json`。43 个候选座位键与现有门店代码未重写，初始地图未发布。旧订单 ID 无来源映射，继续待审。集团注册表暂未登记 `seat_id`，门店候选座位键按本模块上下文保留，集团归属待业务确认。包内模拟结账与集团 `payment_event_id` 无绑定。
- 原包 28 项全过。集成 30 项以包内受控 V9 和合成 V9 两种来源分别通过，包含 HTTP 门店拒绝、开桌至模拟结账、外键与 A/B 参考读取替身。SQLite 一致性备份及隔离读取恢复通过。Python/JS/Bash 静态检查、架构检查、本地版本与失败回切模拟通过。现场座位、调酒计时显示、多浏览器缓存、生产并发和真实支付未验收。
- 其他聊天的 EdgeOne V13、CloudBase 表、供货、标签、人事、督查、营销及资本源码未在当前交付范围找到，待独立接入。合成预览继续独立存在。
- 生产 V2.9 未接触。Lighthouse 仅有本地模拟，当前沙箱无法写入 `/run/systemd` 完成主机级单元验证。实际服务、路径、权限、端口、代理及备份未验。CloudBase 缺少授权、实际表与恢复证据，迁移版本无，A/B 未接云库。若需撤回，关闭 PR 或在合并后回退集成提交；独立 staging 的回退见 `platform/lighthouse/bsv1/`。

## BSV1 对客菜单 V13.1 集成

**日期** 2026-11-18（北京时间）。基于 PR #1 的 `integration/bsv1-handoff`，回退基线 `7edbd5bee4f4271d9b4753c6c813896b36f33e21`。撤回本次变更可关闭菜单 PR，已合并时按提交回退。

- 交接包 35 个文件，18 个映射至工程，原始压缩包及缓存留于来源区。逐文件证据见 `ingestion/sources/bsv1-menu-v13-1.json`。顾客源码位于 `apps/guest-web/bsv1/site/`，POS 私有菜单继续用 `/menu`。
- 原包清单、发布内容、维护、运行、JS 语法和浏览器测试实测通过。集成后 320/390/768 浏览器交互、390×844 HTTP 视觉比较通过，稳定渲染后截图与随附 V13 Makers 基准逐字节一致。15 条风味文案按永久 ID 并与 V13 文案逐项对应。缺少外部 V1.2 数据库导出，未运行其可选对照。
- 原始 BSV1 V9 由 POS 读取器重新生成的 84 项所有公开字段（含 C AJ 价、K 参考价和空价）及四门店均匹配快照。63 C（52 有价）及 21 K（20 有价），无差异。BSVF 是精酿记录，cocktail 界面按原版仅选择三家鸡尾酒吧；交接 ZIP 无 `/craft/` 源码，精酿营业展示未核验。集团 `catalog`、`organization` 权威归属保持不变。
- `DB-A-PUBLIC` 继续读取单一随包静态快照。超时、同源受控回退和敏感字段拒绝已用测试替身验证，当前备用保持未配置。CloudBase 没有实际授权或表及恢复证据，实时 API 未接通，生产迁移版本无。
- EdgeOne 构建输出为十个白名单公开文件，重复构建 ZIP 一致。仅可用于拟议独立预览，Makers 项目、权限、正式域名和双路由须现场确认，补齐 craft 发布资源及实机验证后才可审批更新。未改现网、DNS 或 Lighthouse。
