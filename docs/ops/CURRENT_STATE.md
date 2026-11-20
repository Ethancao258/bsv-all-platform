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

## 供货、库存与督查 V2.0

**日期** 2026-11-18（北京时间）。基于 PR #2 的 `integration/menu-v13-1`，回退基线 `c24284b6a3a06e09515ae253d03a54681f803083`。集成分支 `integration/supply-v2`。未部署或迁移。

- ZIP 校验、原包清单和 31 个文件 SHA 已登记。26 个来源文件映射纳入工程（含改编）。V9 历史参考只提交 17 个 P 与 50 个 M 固定 ID 的脱敏索引，无真实数据库、照片、秘钥或人员原件入库。以 POS 的 V9 读取器核对：17 个 P、50 个 M 历史样本及 V13.1 的 84 个 C/K 商品和四门店 ID 均匹配。没有上线真实 POS 扣库或迁移历史记录。
- 代码位于 `services/api/supply/`、三个既有 UI 入口及 `integrations/vision/`。同一配送事务支持备货、分批扫码收货、库存及在途守恒、带 actor 的幂等日志。门店五档观察不改账，六项自检和独立复核分权，检查/被检查人员不能批准本人涉及的独立复核。
- 修复旧身份缓存和待同步授权范围缺失。读取主备或缓存只作观察，待同步经本人及同授权范围重新认证。上游未返回正式提交时不报成功。图片默认本地二维码，外部需服务器开关和单次许可。D/E 生产事务、G 通知、已批准采购/自制及 CloudBase schema 仍由公司权威接口核实或接续。
- 原包 20/20。集成 27/27，包括两员工并发、10 发 9 收、跨员工/门店及撤权重放、六项检查复核、视觉边界、契约、Fernet 快照及 AES-GCM 测试归档恢复。PG 归档测试使用命令替身。实际 loopback Uvicorn 健康与三个入口通过。端口由环境及服务主管统一配置，测试由 OS 分配临时端口。
- CloudBase 与 Lighthouse 暂无正式授权。A–G 真实 API、主备、新库存账本、反向代理、恢复与视觉服务均待验。候选 SQL 仅保存在契约目录。Issue #3 继续记录遗留与本批证据。

## 统一人员身份 V2.0 R2

**日期** 2026-11-18（北京时间）。分支 `integration/identity-v2-r2` 基于仍未合并的供货 PR #4。回退基线 `b7398d5527052932dde53b0313a18c570250b87f`。生产数据库、V2.9 与已有对客服务未改。

- 67 个文件（66 个原清单条目及清单自身）核对通过，41 个映射纳入工程。来源逐文件哈希见 `ingestion/sources/identity-v2-r2.json`。TR 归 workforce，派生 EMP/BM 共享后缀。源 OpenAPI 40 路径，集成 43 路径。
- 隔离 PostgreSQL 17.12 实测 15 张业务候选表、1 张隔离账号测试表及 Alembic 账本，迁移上/下/重建、120 人并发分配与同请求重试、事务回滚、历史不可变、跨店/跨法人、BM 降权与会话撤销、B 只读及真实 pg_dump 加密与新库 pg_restore 均通过。CloudBase G0/G1 前不创建正式 DDL。
- 原包 39/39，集成 42/42。真实 HTTP POS 试点验证 TR 拒绝、EMP 门店和岗位资格、开桌/草稿/下单以及撤销后即时拒绝；供货与督查通过同一实时身份服务，D/E 使用受控替身。旧码预检、批次提交、回退及联调日志均为合成数据。
- 修复 R2 恢复命令未传数据库、并发重复证明复核窗口与永久记录删除保护；隔离映射预检拒绝同一批重复条目及无归属法人记录，提交采用预检规范化结果。备份权限、实际组织部门、真实自然人去重、CloudBase Auth JWKS、现存表与权限对照、Lighthouse 代理/证书/端口及生产恢复仍待验。完整 POS 动作权限和真实 D/E 未纳入本次试点。
- systemd 与 HTTPS 反代为候选，隔离 Uvicorn 启动、健康检查与两入口通过后方可进入有权限的 staging 验收。关闭未合并 PR 可撤回；生产以后需核实备份和官方迁移回滚。

## 集团数据库契约预检 v1

基线为仍 OPEN 的身份 PR #6（73185dc0236d43e5c666afee8dc0ae40b81749fc）。分支 integration/db-contract-preflight。既有 PR 未合并，生产未部署或迁移。

- contracts/database/ 中登记 66 个既有权威键的交叉映射、按实测反射生成的字段字典、事件边界、冲突与回退门槛。CloudBase 真实表全部 UNKNOWN_G0；cloudbase/audit 新增只读元数据 SQL。
- PG17 隔离预检复用身份原迁移和真实加密恢复，POS 身份 HTTP 使用 PG A，POS 订单仍由 SQLite 承接。供货 API 对接写入 PG 候选表的 D/E 测试替身，发 10 收 9、幂等、权限、恢复后重放及观察不改账通过。菜单保持冻结公开投影。
- 发现供货 UI 的 id/code 别名无法读取中央候选 shipment_id/package_id。接口层做显式映射，拒绝 ID 冲突及把库位误当门店。没有改历史标识或生产接口。
- 仍受阻：CloudBase G0/G1、全域实际 PK/FK/RLS/GRANT/迁移/备份、生产 POS 上传消费与支付、真实 D/E 权限/事务、配方版本、门店/库位及旧人员 ID 权威映射。关闭未合并 PR 可撤回；隔离库自动销毁，生产回滚从已验恢复点执行。

## 2026-11-20 Lighthouse 私有集成测试版

- 远端 PR #7 基线已核对为 `97d2c7c884e60b72327c89b7057e5cf50082e59d`。本批代码使用 `integration/lighthouse-internal-stage`，以 PR #7 分支为 base，完整 SHA 见本节提交及对应 PR。保留 14 个根目录与既有 ID 归属。
- USER_REPORTED · 经营负责人终端显示 Lighthouse 北京 Ubuntu 24.04.4，`bsv1-preview.service`/8765 和 `bsv-all-bsv1-stage.service`/8767 均 active。后者有健康响应及独立 `STAGEADMIN01`，主仓库只读 Deploy Key 和 PR #7 checkout 已配置。Codex 未直连该主机，状态可能变化。
- USER_REPORTED · 经营负责人在 CloudBase 上海目标环境的只读 SQL 取证记录 PostgreSQL 17.11、36 张表、public 中 10 张 BSV 表及其字段、主外键和约束。10 张表均未启用 RLS，anon 全部有 SELECT，authenticated 和 service_role 有广泛权限。bsv_products 的有效 ACL 经数据库函数核实。此证据更新此前 UNKNOWN_G0 的对应项。真实数据 API 可达性、JWT/JWKS、迁移账本和备份恢复仍未知，Codex 凭据未连接生产。 [Issue #3 权限证据](https://github.com/Ethancao258/bsv-all-platform/issues/3#issuecomment-6981854517)
- PASS_ISOLATED · 真实 PG17 候选迁移和回退、120 并发发码、重试/事务/约束、撤权、加密 dump 与空目标恢复通过。隔离 HTTP 以独立 venv 运行身份、供货、POS 和统一入口，测试 BM/EMP 派生、临时别名、真实登录和未付款订单、门店隔离、供货/督查同 Cookie 认证、跨站拒绝和撤权。POS 仍有独立 PIN 步骤。
- MOCK_ONLY · 版本符号链接回切及失败恢复已模拟。PG17 供货及督查合同替身验证 10 发 9 收的守恒、收货幂等、断连和禁止自审。BLOCKED · D/E 没有运行中的权威事实 API。测试入口只接 B 身份源，不返回中央成功。A/C 目录仍未提供，CloudBase 生产迁移为无。
- NOT_RUN · Lighthouse 新单元安装、实际端口与主机 systemd 回切。隔离环境无运行中的 systemd PID 1。新部署操作和合成数据边界见 `platform/lighthouse/internal-stage/`。本批无云端写入、部署或生产配置修改。


## 2026-11-20 Lighthouse 首次实机验收（USER_REPORTED）

证据来源：经营负责人粘贴的北京 Lighthouse Ubuntu 终端输出；仓库维护者未直接登录服务器。本节只记录可从该输出确认的状态，不等同于生产可用或全链路真实业务验收。

- PASS · 依赖条件：PGDG PostgreSQL 17.12、Python 3.12 venv 已安装，旧服务 `bsv1-preview.service`/8765 和 `bsv-all-bsv1-stage.service`/8767 保持 active。此前 PR #8 的 8ff2e62 部署在系统服务中出现 `current/platform/...` 找不到启动脚本；下次部署又因受限子进程 PATH 无法解析 `runuser` 停止。
- FIX_COMMITTED · PR #8 的 `ceb0de0` 修复 `/usr/sbin/runuser` 绝对路径，`13dad3d` 修复 systemd 指向 `current/src/platform/...`；`ba970d6` 增加两项路径与受限 PATH 回归断言。上述 GitHub 修改均尚未合并 main；验收部署的代码 SHA 为 `13dad3df84eacd83ffd9ddc8112cbcee6c3256ec`。
- PASS_HOST · 经营负责人提供的实机输出显示 `PREFLIGHT_OK`、`VERIFY_OK: loopback routing, health and anonymous access checks`、`DEPLOYED_INTERNAL_STAGE 13dad3df84eacd83ffd9ddc8112cbcee6c3256ec`，最终 `BSV_ALL_DEPLOYMENT_ACCEPTED`。五个新 `bsv-all-internal-stage@{postgres,identity,pos,supply,ingress}.service` 均 active，对应端口 18764/18761/18762/18763/18760；两个原服务均 active。属于启动与匿名访问就绪验收，**尚未在操作员自己的 Windows 浏览器完成 SSH 隧道、人工登录和真实操作验收**。
- ISOLATED_ONLY · 合成管理员 `reviewer1`/`reviewer2` 生成 `TRA0001`/`TRA0002`；这些仅为隔离数据，不得迁入正式终身主码空间；POS 使用测试 V9 和 SQLite。CloudBase 生产库、正式收款、中央库存 D/E 权威账本和独立督查实际复核写入尚未接通，生产 GO 为否。
- NEXT_GATE · 在操作员本地以 SSH 转发 18760，验证 `/staff`、`/pos`、`/hq`、供货/督查读界面、登录/撤权、明确 503 写入拒绝；另做 Lighthouse 真正故障回切、PG17 加密备份-恢复、跨服务审计及安全门禁。密钥、PIN、数据库密码禁止写入 GitHub 或日志报告。GitHub 文档变更比现网运行 SHA 更新时，必须分别记录代码头版本与已部署版本，不得视为自动热更新。


## 2026-11-20 Windows 实机浏览器入口验收（USER_SCREENSHOT）

- PASS_BROWSER_UI · 经营负责人提供的 Windows Chrome 截图显示浏览器已成功呈现 `http://127.0.0.1:18760/` 的“BSV ALL 内部测试”主页，并列出员工登录与个人中心、总部身份管理、门店 POS、供货与库存、独立督查、电子菜单六个链接。由截图可确认浏览器到本机 18760 的页面可用，尚不能单凭截图确认各子模块的登录、业务调用及权限正确。
- OBSERVATION · 同一截图的 PowerShell 会话显示 SSH 认证密码提示，当前这一个终端会话是否已完成认证不能由截图判定；实际浏览器页面可通过已有有效隧道或独立会话提供。该截图不附带到仓库，不存储服务器公网 IP 与凭据。
- NEXT_GATE · 以本机私有 SSH 隧道登录 `/staff`，用仅在隔离环境生成的 `reviewer1` 凭据验证身份页面；再进入 `/hq` 并在后续单独执行 POS 与供货/督查跨模块验收。禁止真实客户、员工和收款数据进入测试环境。
