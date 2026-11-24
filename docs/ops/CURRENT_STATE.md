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


## 2026-11-20 Windows 身份中心登录验收（USER_SCREENSHOT）

- PASS_BROWSER_LOGIN · 经营负责人在Windows浏览器经SSH隧道打开统一入口 `/staff` 并使用隔离测试身份成功登录；页面明确显示“登录成功”“已登录”。
- PASS_ISOLATED_IDENTITY_DISPLAY · UI展示单一自然人测试主码 `TRA0001`、派生 `EMPA0001` 和 `BMA0001`，后缀一致。有效法人范围 `DEMO_LEGAL`；测试资格 `BM_MANAGEMENT`，来源 `SYNTHETIC-BM-TRA0001`，并列出 HQ 审计、人员、资格、任命和授权操作列表。截图证明页面会话和身份读取渲染成功，不单凭UI断言服务端所有授权及撤权已实机覆盖。
- DATA_BOUNDARY · 该人员是隔离环境合成管理员，不代表真实人员或正式终身编号分配。用户截图不包含明文测试密码；绝不将私有凭据写入工程档案。
- NEXT_GATE · 浏览器沿用当前会话访问 `/hq`，核验总部后台授权读取与界面；确认后再执行双管理员审批及POS/供货的跨模块实机授权测试。测试库与CloudBase保持隔离。


## 2026-11-20 Windows 总部后台登录与只读展示验收（USER_PASTE）

- PASS_BROWSER_HQ_VIEW · 用户从同一Windows浏览器隔离测试会话进入 `/hq`，看到“人员身份与授权管理”、`DEMO_LEGAL` 法人范围及HQ管理权限列表；网页已显示“我的操作权限”对应的十六项权限及管理限制“不能批准自己提出的申请，不可自行提升 BM”。来源为用户提供的浏览器页面复制文本，未直接证明每项授权写入服务端执行。
- PASS_BROWSER_CAPACITY_VIEW · 隔离PG数据库页面显示人员编号配额“已使用 2 / 总容量 239,976 / 剩余 239,974”；与上一步独立测试生成两个合成管理员一致，但不能外推为正式生产号码池的唯一分配结果。
- UI_READY_NOT_WORKFLOW_VERIFIED · 注册与发码、任职与资格、EMP/BM、跨店授权、旧码预检、账号安全、人员查询入口可见；本轮没有提交审核、发码、任职、授权、撤销或其他写操作。
- NEXT_GATE · 使用“人员查询”中的“TR码或名字”只读查询 `TRA0002`，确认 `DEMO_LEGAL` 合成第二管理员可检索。之后再按最小变更原则测试双人审批、POS、供货/督查权限及撤销。原有8765/8767、CloudBase正式库不变。


## 2026-11-20 浏览器总部人员精确查询验收（USER_SCREENSHOT）

- PASS_BROWSER_HQ_LOOKUP · 操作员在Windows的 `/hq` 人员查询以 `TRA0002` 搜索，截图显示 `TRA0002 · ISOLATED TEST OPERATOR reviewer2`、状态 `active`。证明既有HQ会话在 `DEMO_LEGAL` 范围可调用只读人员检索并获得合成PG身份记录；不代表跨法人限制或审批写入已经实机验收。
- NEXT_GATE · 使用HQ旧码预检执行 `bsv1_pos,SYNTH-STAGE-POS-01,TRA0001` 的仅预览核对（写入0），确认隔离POS的本地人员别名指向同一合成TR后，再通过独立批准的映射提交/岗位权限安排进行POS联调。严禁将该合成关联应用到正式人事数据。


## 2026-11-20 旧POS码只读映射预检（USER_SCREENSHOT）

- PASS_BROWSER_DRY_RUN · 经营负责人Windows浏览器截图显示总部 `/hq`“旧码迁移预检”输入 `bsv1_pos,SYNTH-STAGE-POS-01,TRA0001`，页面返回 `SYNTH-STAGE-POS-01 → TRA0001`、`reviewed · 无冲突`。这是隔离合成POS旧码绑定到合成 `TRA0001` 的预检，未证明创建任何正式或测试别名数据。源码规定 dry-run 写入为0。
- GATE · 接下来使用受控隔离后台身份API，在再次验证 `mode=isolated`、`blocked=0`、`issues=[]` 后才允许创建单条合成LegacyAlias。完成后需测试该TR的POS资格和门店岗位授权，再进行BSVT未付款订单验收。真实员工/客户和CloudBase生产数据库禁止参与。


## 2026-11-20 隔离POS身份别名正式提交与V3交付控制面

- PASS_ISOLATED_HOST_REPORTED · 操作员在Lighthouse上通过隔离身份API `/api/v1/identity/legacy-import/commit` 将 `bsv1_pos,SYNTH-STAGE-POS-01,TRA0001` 写入**独立测试PG**，原始终端输出依次为 `ISOLATED_MODE_OK`、`ADMIN_IDENTITY_OK`、`PREVIEW_OK`、`ISOLATED_ALIAS_COMMIT_OK`、`MAPPING_VERIFIED`。再次预检返回`ALREADY_MAPPED`。这是唯一一个合成别名，不代表POS角色授权或真实人员迁移。无需重复写入。CloudBase正式库本次未触碰。
- CONTRACT_CREATED_GITHUB · ChatGPT已直接提交 `docs/architecture/BSV_ALL_DELIVERY_CONTROL_PLANE_V1.md`、`config/change-routing.json`、`scripts/verify_change_routing.py`、`AGENTS.md`第15条和 `docs/ops/CODEX_WORKFLOW.md`V3，以及CI静态路由检查。GitHub Issue #9作为**V1→V2→V3同一整合任务**的唯一入口。用户明确尚未向Codex实际启动本轮开发，不能把Issue存在当作Codex运行中。
- DELIVERY_NOT_CONNECTED · 当前ChatGPT已有GitHub读写连接，可更新Issue和源码；但尚无直接触发网页版Codex开发会话或从此会话直接SSH部署Lighthouse的获授权执行链。拟议 `bsvctl` 与自动发布控制器是设计，**NOT_IMPLEMENTED**。后续先由Codex实现并经本机实际验证，绝不声称已“一句话自动上线”。
- OPERATING_PRODUCTION_NO_GO · 北京Lighthouse 4核约4GB、40GB现运行七个新旧单元的可用性与资源裕量须实测；真实CloudBase ACL/RLS、备份恢复、跨区域认证、实收支付及D/E库存/督查权威写入仍阻断正式生产。

## 2026-11-20｜Issue #9 V3 唯一集成冲刺

- 源码从 PR #8 的 `0836cca1bc6b829733c43637c622632aad909ac4` 继承，基线七项 CI 成功。V3 分支 `integration/sprint-v3` 保留既有修复和 14 个一级目录。实际候选 SHA 与 CI 以 [Issue #9](https://github.com/Ethancao258/bsv-all-platform/issues/9) 对应 PR 为准。
- 工作包 A 负责身份、旧码和 POS API。旧码同向重试写入 0，反向关联冲突拒绝。隔离审批人和本人分离。批量 POS 验收用独立 run ID 记录订单并归档本次桌次，支付拒绝，跨店与撤权后拒绝。复用既有 TR/EMP/BM，第三位合成审批员仅用于测试批准。
- 工作包 B 负责工作台、员工、总部、POS、供货及督查的中文界面。权限来源为已登录人员的有效授权。D/E 仍不可写，界面与 HTTP 保留明确阻断。工作包 C 负责主机预检、发布检查点和回切。主集成负责批量验收驱动、路由和发布控制器、CI、审查。
- PASS_ISOLATED · 先前已提交的合成别名在真实隔离 PG17 与四个 HTTP 服务上通过两轮验收。同后缀、总部跨法人拒绝、岗位两人审批、POS 测试 PIN 二次认证、未付款下单、支付拒绝、供货/督查身份及 503 写入门槛、撤权和登出均由脚本验证。CloudBase 正式库和收款接口未连接。
- HOST_NOT_RUN · V3 主机部署、批量验收和安全回退均未执行。实际已部署 SHA 最近由经营负责人提供，仍为 `13dad3df84eacd83ffd9ddc8112cbcee6c3256ec`，旧服务 8765/8767 的 active 也是该次主机报告。V3 的新主机结果必须以实际 `bsvctl.py` 和 `acceptance.py` 回执为准。
- 手动交付控制器和注册表查询已实现。批准的 GitHub CI 导出由操作者核对，Lighthouse 仍只有只读拉取能力。对话自动启动 Codex、GitHub 自动触发主机、主机自动回写 GitHub 和生产迁移均为 NOT_CONNECTED。

| 页面 | V3 主要文案与反馈 |
|---|---|
| `/` | 链接列表改为“BSV 工作台”，依据有效会话展示角色、门店和下一步。供货暂未启用，督查仅可核对范围。 |
| `/staff` | 用“你的人员编号”、员工及管理身份状态解释同源编码。登录、申请和退出就地反馈，技术详情可展开。 |
| `/hq` | 旧码预检显示正在核对、仅检查尚未保存或已关联无需重复提交。业务表单显示已确认编号及下一步，网络结果未知时先查记录。 |
| `/pos` | 内部试单只允许记录未付款订单，页面显示“尚未收款”。 |
| `/supply-ui/` | 中央账未连接时保留个人权限查看和两类工作入口，提交不可用。 |

- PASS_ISOLATED · Chromium 在 375px 和 1440px 实际操作：匿名首页、员工登录与授权、督查只读提示、POS 二次核验和未付款提交、总部查人和已有别名预检。浏览器模拟请求中断验证“结果暂未确认”及保留表单输入，未执行该次写入。桌面、手机和总部截图由 CI 归档。
- PASS_ISOLATED · 隔离 PG17 上实际完成加密备份、校验及恢复，合成 POS SQLite 实际完成一致性快照。发布与回切的模拟回归为 MOCK_ONLY。Lighthouse 新版本安装和回切仍为 HOST_NOT_RUN。按部署说明在主机查看发布清单与批量验收回执。

## 2026-11-20｜Issue #11 V4.1 学院、排班、设备点单

- 已部署基线由经营负责人确认是 PR #10 的 `0e8b3c00544ccd533eebd1258598f2622c5b0984`，V3 主机结果为 `STAGING_ACCEPTED`。V4.1 分支从该完整 SHA 开始。V4.1 Lighthouse 新版部署、实机业务验收、回切及恢复仍为 `HOST_NOT_RUN`。
- 源码分工。学院、资格、排班和设备权限归身份及学习服务，POS 按统一会话及设备和班次实时取权。工作台和学院沿用已登记路由。导入预检和发布回退使用既有目录和证据机制。权威与数据字典见 `contracts/academy/V4_1.md`，十项反例审查见 `docs/ux/V4_1_DECISIONS.md`。
- 隔离迁移新增 `bsv_academy_0002`，不迁移生产，也不改变现有 TR、组织或商品登记。V4.1 安全回切采用保留追加数据库结构的代码回退，发布前检查点保存 PG17 加密档、POS SQLite 快照及隔离私有媒体。V3 与 V4.1 使用不同本地 POS 会话名。
- 员工先登录统一账户，学院展示通用课和已获准的门店课。独立核验者确认实操后，培训凭证结合岗位授权才可排班。负责人建班、另一获授权负责人批准，员工确认后在当班时间登录本店已登记终端。当前隔离范围为 BSVT、BSVS 与 bartender。合作公司及未核实的店级归属保持拒绝。
- `IMPORT_NOT_RUN` · 公司、门店、旧码、人员及课程等模板位于 `ingestion/v4-1`。隔离预检校验权威快照引用、字段、冲突、有效期及幂等。隔离提交保留审查回执，不写集团权威事实。未获批准的现实资料和课程原件保持阻断。
- 审批边界。隔离环境可验证合成工作流。真实员工试点须由负责人批准最小资料范围、备案/HTTPS、私有访问、扫描、加密备份和恢复。正式营业还缺 CloudBase G0/G1 和 ACL/RLS 修复、真实收款专项批准、D/E 权威写入及五店容量证据。公开鸡尾酒菜单保持原发布物，只有私有同源入口提供工作台返回。
- `PASS_ISOLATED` · 两轮 PG17 + SQLite 真实 HTTP 验收验证同一 TR 在 BSVT 两台独立注册终端创建未付款订单、重复请求防重、订单审计、设备撤销以及 BSVS 独立培训和班次解锁、撤权失效、跨店排班冲突和北京时间跨午夜。合成旧码保持零写入，追加迁移后复跑 V3 身份服务验证既有记录仍可读取。
- `PASS_ISOLATED` · Chromium 在 320–1440px 的八个宽度验证工作台和注册终端流程，覆盖浏览器模拟缩放、文字放大、窄高视口及菜单返回；真实移动设备软键盘仍待现场观察。导入预检 7 项、发布控制和部署回归 16 项通过。GitHub 精确 SHA、CI 和截图见 [Issue #11](https://github.com/Ethancao258/bsv-all-platform/issues/11) 的集成 PR。


## 2026-11-22｜酒水Excel接入开发（分支 `feature/bsv1-excel-catalog`）

- 已接收原始附件《BSVALL酒水套餐数据库.xlsx》，文件 SHA-256 与提交说明一致：`4ed9bc164981f267997bd146df54d27ae22fbdc9cc1c850776daed83d34c8e82`。原文件未提交 Git。
- 已用现有 `bsv_v9_import.py` 在本地解析器检查七张工作表。原表记录计数：C 63、P 17、M 419、K 21、R 65、Q 0、T 4；T 中保留 BSVM、BSVS、BSVT、BSVF，Q 无报价记录。C 内容审核/上架状态未达到销售授权条件；Excel里有售价不等于允许POS销售。R 只通过“出品关联ID”关联C，无法由名称补建缺失物料ID。
- 本分支在现有 POS SQLite 目录下新增受私有权限保护的版本目录配置：`/var/lib/bsv-all-internal-stage/pos/catalog`，位于版本发布目录之外。版本文件以SHA命名，先验证全部工作表，再事务同步SQLite；人工激活锁住版本，CLI支持状态、回退、显式解除锁定。历史订单和门店地图不由导入器改写。
- POS只读目录API与无订单配方查询正在本分支实现；真实服务器未改动、未验证。
- CloudBase自动更新仍为 BLOCKED：当前网页版没有可调用的官方CloudBase文件API/OAuth工具；本轮信息没有提供可核验的Bucket ID、对象 fileID/路径或可用服务端身份。未设置匿名公开下载、未添加猜测的定时任务。
- 本地完整测试尚未执行（当前执行容器写层无可用空间，无法启动本地构建）；最终提交后的GitHub Actions结果将作为CI证据。Lighthouse HOST_NOT_RUN。


## 2026-11-23｜统一数据访问架构准备（PR #40）

- **代码提交 `dfce0e7a233239208d5a7330a1191bc478e76b35`** 延续 PR #40 的 `feature/bsv1-excel-catalog`，没有创建新 PR。新增 `config/data-contracts.json`，引用原 `data-ownership.json`、身份 A/B/LOCAL 注册、供货 A–G 注册、POS 领域契约及现有 API 契约；没有复制一套实体所有权。
- `BSV_DB_URL` 现登记为 PostgreSQL 17 / `bsv_all_prod` 的正式入口；identity A 与 Customer Growth 在明确配置时可读取该 DSN，旧 `BSV_DB_A_URL`、`BSV_GROWTH_DB_URL`、POS `BSV_DB_PATH` 和供货 A–G 配置继续兼容。隔离模式拒绝中心 DSN，POS 当前订单/座位 SQLite 写入源未改变。CloudBase 的10张表仍是 `UNKNOWN_G0`，未连接、未建库或执行 DDL；正式字段字典等待 WorkBuddy 审查。
- POS 员工界面查询已切换至受会话保护的 `/api/v1/catalog/products` 只读契约；搜索、商品详情和无订单配方接口输出 `contract_version` 与注册表语义字段。旧 API 保留。新适配仍读取当前 POS SQLite/Excel投影，没有声明任何未核实 PG 表或列。
- 导入版本已有分步候选状态：`archive → preview → validate → commit-candidate → publish → rollback`。发布前只校验并保留私有SHA版本/归档，不修改活动SQLite；`publish` 复用既有事务和回退能力。旧 `stage` 命令改为只归档、校验，不再隐式切换活动内容。私有 Lighthouse 隔离配置增加 `BSV_IMPORT_ROOT` 和 `BSV_PRODUCT_MEDIA_ROOT`；产品图片优先按永久商品ID和原文件名从发布目录外持久路径读取，并拒绝路径穿越/软链接，旧release路径仅作只读回退。
- **本地验证 PASS** · `bash tests/bsv1/check.sh`：39项POS测试 + 4项数据契约测试通过；`python3 tests/internal-stage/test_deploy.py`：26项部署预检测试通过（1项按既有条件跳过）；`verify_architecture.py`、`verify_change_routing.py`、JSON/语法检查通过。Customer Growth 单元测试因此执行环境未安装 SQLAlchemy/pytest，标记 `LOCAL_NOT_RUN_DEPENDENCY_MISSING`；PR CI 将运行有锁定依赖的对应作业。
- **未执行** · PostgreSQL正式建表/迁移/导数、真实CloudBase连接与对象下载、Lighthouse配置修改/部署、媒体上传均未执行，主机 `HOST_NOT_RUN`。后续须先通过 WorkBuddy 字段字典、再做真实环境 G0 核验及备份/恢复证明；CloudBase私有对象ID/服务端授权及每天05:00同步仍未实现。
- **GitHub CI PASS** · commit `8b78c51b1a5a13939992aa436f90e252586b38c6` 的 [主验证 run 45084992980](https://github.com/Ethancao258/bsv-all-platform/actions/runs/45084992980) 九项全部通过；[Customer Growth run 45084992992](https://github.com/Ethancao258/bsv-all-platform/actions/runs/45084992992) 通过，弥补本地缺少依赖的未运行项。当前分支在该提交后仅有本状态记录变更，PR #40 保持 Draft，不自动合并或部署。


## 2026-11-23｜WorkBuddy V2.2 PostgreSQL 17 隔离接入（PR #40）

- **基线已核对** · PR #40 分支 `feature/bsv1-excel-catalog` 从 `6bfa47fde3da4469b6b923c0e134445c06944fbf` 开始，工作树原先干净；Draft PR 和基底均保持不变。本轮未操作 CloudBase、Lighthouse、正式数据库或生产服务。
- **来源验证** · 外层交接 ZIP SHA-256 `d0b40f376880791a4feab9d8dff165c6b1a401db823781cb10da7da46cb95d3d`；内层 WorkBuddy ZIP `3f98fbe12eacdca481d1e7b3350a59410da7f1116c74a75a1c7b93fe63a0e5a1`；源 Excel `4ed9bc164981f267997bd146dfd54d27ae22fbdc9cc1c850776daed83d34c8e82`。WorkBuddy 包验收工具实际输出 `47 PASS / 0 FAIL`。字典381唯一字段与统一注册表逐项比较；来源映射16,815、公式6,275（数组公式4,978、空缓存2,692）；原始输入记录589、辅助来源记录、21套餐槽位、84门店研究及C/P typed recipe links均经包内数据验证。R页链接为63条C及 `R000048→P000003`、`R000051→P000004`。这是来源包静态证据，不是数据库入库回执。
- **代码候选** · 扩展唯一 `config/data-contracts.json` 的381字段映射，命名空间为 `catalog/core/audit`；完成 WorkBuddy 隔离编号迁移、事务导入器、同SHA幂等、完整来源记录/字段/公式/映射导入、raw 状态保护、失败事务回滚与版本指针回退。正式 `cloudbase/migrations/` 未改动，WorkBuddy 原始数据未入Git。
- **读取边界** · POS既有 `/api/v1/catalog/products` 与配方路径增加显式隔离 PostgreSQL 17 只读适配，查询经稳定语义键映射；在设置 `BSV_APP_ENV=isolated`、`BSV_CATALOG_READ_SOURCE=postgres` 和loopback `BSV_DB_URL` 时读取活动PG资料，PG故障返回503而不回退Excel/SQLite。POS订单、座位和付款快照仍只由原SQLite写入。PG原始资料全部标记 `IMPORTED_RAW`、`sale_enabled=false`；菜单公开预览不读该私有PG目录；采购/成本字段按字典隐藏。媒体仍从持久目录读取，不从release目录提供。
- **本地验证 PASS** · 合同测试5/5、导入安全测试2/2、POS回归45/45（PG容器专属4项在本机因无PG服务而跳过）；`verify_architecture.py`、`verify_change_routing.py`、Lighthouse隔离部署模拟26项（1项原有条件跳过）、Python/JS/Bash语法和 `git diff --check` 通过。包验收工具47/47。执行环境无运行中Docker daemon、PostgreSQL服务/客户端且空间不足，因此本机没有真实执行PG DDL或导入。
- **GitHub CI PASS** · 提交 `5dfebb869df142f011e33508e0c1aa307b1c9e69` 的 [主验证 run 45096723579](https://github.com/Ethancao258/bsv-all-platform/actions/runs/45096723579) 九个 job 全部成功；`bsv1` job 的真实 PostgreSQL 17容器迁移、只读角色、typed C/P recipe、POS HTTP PG读取、SQLite缓存为空、匿名拒绝、菜单隔离、断连503、失败事务原子性和版本指针回退测试通过。另有 [Customer Growth run 45096723576](https://github.com/Ethancao258/bsv-all-platform/actions/runs/45096723576) 成功。PG容器使用合成数据；真实完整WorkBuddy数据导入仍必须在批准的隔离PG执行，CI合成测试不替代实际数据导入回执。
- **资源/业务状态** · `PG17_FULL_DATA_IMPORT=NOT_RUN`；`HOST_DEPLOYED=NO`；`BUSINESS_VERIFIED=NO`。Lighthouse当前服务、磁盘/内存、隔离PG容量、备份/恢复和浏览器HTTP均未由本轮工具核验；CloudBase G0/官方迁移历史仍UNKNOWN。隔离数据库 `bsv_all_prod`、loopback PG17、备份空间及读写角色创建均待服务器授权和预检，不得复用 `bsv_identity_isolated_internal`。
- **回退** · 程序按受控发布器退回前一release；原SQLite业务库和媒体不随代码覆盖。PG导入以单事务提交，失败自动回滚；活动资料回退只切换 `catalog.active_content` 指针并保留历史版本。不得用本迁移删除或回滚正式CloudBase数据。

## 2026-11-23｜PR #40 V3.0 数据落地与更新闭环收口

- **基线核对** · `feature/bsv1-excel-catalog` 的本地/远程起始HEAD均为 `0d814f62587132c78c8ac648981a862ef2b1dd56`；PR #40 仍为OPEN Draft，目标分支 `feature/g1-three-store-identity-pos`。未改主架构、永久ID或现有生产数据。
- **来源实证** · 外层交接ZIP、内层WorkBuddy ZIP和Excel哈希与 `ingestion/sources/workbuddy-v22.json` 一致。内层包本轮重新核验：归档与解压文件完全一致、逐文件SHA/大小与manifest匹配、字段契约381项匹配；清单行数核实为C63/P17/M419/K21/套餐槽21/NPS84/R65/Q0/T4，辅助数据dictionary399/legal449/calc597、映射16815、字段381、公式6275、source_record694。原始包与Excel未提交Git。
- **导入门禁** · 移除导入程序中绑定V2.2内容的固定ZIP/XLSX SHA和行数；兼容版本以manifest声明、实际文件哈希、字段契约和ID外键核验。导入需root保护密钥签发的24小时审批JSON，绑定包/清单/契约/审批操作者/变更号/预期活动版本，并记录审批字段；审批失效、被篡改或活动版本发生竞态时拒绝。相同来源SHA重复请求保持幂等；资料版本回退也需要独立签名审批。
- **数据库权限与发布配置** · 增加隔离迁移 `0002_catalog_reader_least_privilege.sql`，撤回原宽表读授权，建立基础/保密过滤视图并禁止POS读取原始审计JSON与受限采购字段。隔离发布器在现有PG17 cluster内预置独立逻辑库 `bsv_all_prod`、runtime/importer角色和分离凭据；只有POS `pos.env` 配置 `BSV_DB_URL`，身份仍使用 `BSV_DB_A_URL`。HBA扩展限127.0.0.1/32，须精确匹配受管旧策略，先保留原策略，校验失败则恢复；实际服务器未执行。
- **备份准备** · catalog采用独立私有目录/密钥和现有AES-256-GCM备份工具；checkpoint核验会验证catalog加密备份的SHA和无写入解密完整性。真实备份创建、临时PG恢复演练及服务/磁盘/WAL检查未运行，不能据此认定恢复能力已验收。
- **本地验证** · BSV1 `check.sh`：46 passed、4 skipped（4项PG17测试因无Docker跳过）；合同测试5 passed；Lighthouse内部阶段/控制面31 passed、1 skipped（Ubuntu 24.04系统Python3.12专测）；包清单程序重验通过。额外身份备份pytest未能在本环境加载，因为缺少SQLAlchemy依赖，本地NOT_TESTED；交由CI安装锁定依赖验证。
- **未执行项** · 当前容器没有Docker daemon/PG17服务，PG17新迁移、最小角色访问、HTTP网页实际读PG尚待GitHub Actions job。当前Codex没有Lighthouse/TAT/SSH操作授权；主机实际版本、服务、磁盘、备份恢复、PG角色与 `127.0.0.1:18760` 浏览器数据来源均 `HOST_NOT_RUN/UNKNOWN`。真实V2.2数据未入库，`CODE_DONE`仅指代码候选；`CI_PASS`待新SHA的Actions；`DATA_IMPORTED=NO`、`HOST_DEPLOYED=NO`、`BUSINESS_VERIFIED=NO`。CloudBase、真实订单/员工/会员数据、上架与收款均未触碰。
- **本轮回退** · 代码通过PR #40撤回，不合并/不部署。正式隔离数据库创建后，程序版本由受控发布器回退；内容版本只通过签名审批切换 `active_content`，保留两版数据。HBA升级附有原文件受控备份并拒绝未登记漂移。此回退尚无真实主机演练证据。

## 2026-11-23｜PR #40 V3.0 最终代码与验证状态

- **最终代码候选** · `feature/bsv1-excel-catalog` HEAD=`852d8c86bf782ceda4023dab3da9061381e15237`，PR #40 仍为 Draft、未合并。保留基线 `0d814f62587132c78c8ac648981a862ef2b1dd56` 的既有历史。该SHA的 [GitHub Actions主验证 run 45106816835](https://github.com/Ethancao258/bsv-all-platform/actions/runs/45106816835) 九个作业全部成功；[独立API/合同 run 45106816833](https://github.com/Ethancao258/bsv-all-platform/actions/runs/45106816833) 成功。
- **CI实际覆盖** · `bsv1` 作业使用隔离 PostgreSQL 17 容器，迁移 0001–0003、事务提交/重放、最小角色和受限字段、C/P双类型配方关联、POS HTTP读PG、匿名拒绝、SQLite商品缓存未启用、菜单未上架、PG断连503、导入失败原子回滚、经审批的活动版本切换/回退均通过。此为合成CI数据库证据，不是服务器或真实WorkBuddy数据入库证明。
- **本地测试** · Python语法编译、4项导入审批/来源安全单元测试通过；`bash tests/bsv1/check.sh` 为46 passed、4 skipped（无本地PG容器）；内部部署与控制面测试31 passed、1 skipped；架构、变更路由、包manifest与 `git diff --check` 通过。完整PG17测试由Actions执行。
- **实际状态** · `CODE_DONE=YES`（集成代码候选）；`CI_PASS=YES`；`PG17_REAL_V22_IMPORTED=NO`；`HOST_DEPLOYED=NO`；`BROWSER_VERIFIED=NO`；`BACKUP_RESTORED=NO`；`DATA_UPDATE_WITHOUT_CODE=CI_ONLY_NOT_HOST_VERIFIED`；`PRODUCTION_CUTOVER=NO`。本环境没有Lighthouse/TAT/SSH主机操作通道，因此主机状态、容量、服务端PG、备份恢复、导入批次及SSH隧道浏览器验收均 `HOST_NOT_RUN`。未连接CloudBase；未更动订单、身份、会员、支付、生产数据。
- **下一门禁** · 经营者需在受控执行通道中授权一次性访问现有 Lighthouse 隔离主机，范围限定 `/var/lib/bsv-all-internal-stage/` 和已批准隔离 PostgreSQL；无需在聊天中提交SSH私钥、口令或数据库凭据。授权后先读取主机真实状态、备份并预检，再按审核后的操作流程创建隔离库、导入V2.2并执行浏览器/恢复验收。未经此授权不得标为已部署或已验收。

## 2026-11-23｜PR #40 Lighthouse 首轮部署阻断修复

- **故障来源** · 按PR #40 issue comment `7093073996`（业主提供的TAT回执）记录：受控预检和旧版检查点成功；角色校验中止后，发布器回切旧 `f6d8ce9` 并通过健康核验；新版及WorkBuddy导入未完成。当前Codex没有连接主机，本项为 `HOST_REPORTED`，不是独立主机复验。
- **代码修复** · `stage.py` 的成员角色查询筛选 `member.rolname`，结果表示“该角色继承哪些被授予角色”。现在 `bsv_catalog_reader` 的预期继承集合为空；runtime/importer/confidential-reader 三个角色仍按既有最小权限图校验，不新增/反向补做GRANT。`as_user()` 默认从可访问的 `/` 启动子进程，显式服务工作目录继续保留。
- **续跑安全** · 不删除上次失败的 release/work目录、身份或POS检查点、HBA标记、PG角色或 `bsv_all_prod`。现有发布器只在角色/owner/属性与受管HBA校验一致时继续；未知状态拒绝。旧 8765/8767 与身份库不作手工变更。
- **定向与集成验证** · 新增角色方向图与SQL筛选、runuser私有父目录、默认及显式cwd测试全部通过。内部阶段除本地磁盘不足导致的完整归档解包用例未能运行外，其余29项通过、1项按环境条件跳过；GitHub 托管 runner 的完整 `lighthouse-internal-stage` job 通过。`git diff --check`、Python编译与 Bash语法检查通过。
- **代码与CI** · 故障修复提交 `18fa7e1ebf831032666ecffa36e65feb28bd5fa3`；该SHA的主验证 [run 45124215553](https://github.com/Ethancao258/bsv-all-platform/actions/runs/45124215553) 九个作业通过，独立 [run 45124215624](https://github.com/Ethancao258/bsv-all-platform/actions/runs/45124215624) 通过。发布包待绑定最终文档SHA重新生成。
- **真实状态** · 业主TAT报告旧版已恢复；本次Codex无TAT/SSH写入通道。`PG17_REAL_V22_IMPORTED=NO`、`HOST_DEPLOYED=NO`、`BROWSER_VERIFIED=NO`。之前失败留下的role/database/HBA及build目录由受管发布器精确核对续跑；本轮不手动改权限、不删除或覆盖历史文件。

## 2026-11-24｜BSV-A 恢复认证门禁修复与 BSV-B 预览切片

- **BSV-A 代码** · 在 PR #40 继续修复隔离PG17的恢复闭环：恢复专用临时库只允许使用 OS/PG `bsvint-postgres` peer 身份、受管PG17 socket目录及端口 `18764`；拒绝非唯一隔离恢复库或其他端口。run-once恢复后校验与查询改用受管 postgres OS 用户，避开 root→peer身份不匹配；不增加恢复数据库的TCP/HBA白名单。CI测试取消 `trust`，用精确DB/role的SCRAM TCP规则和 `local all all peer`，并检查临时恢复库没有TCP例外。
- **安全验证状态** · Python编译、Bash语法与 `git diff --check` 已通过。此执行环境缺少 pytest、SQLAlchemy、psycopg及可用PG测试环境，新增真实PG17/peer/SCRAM测试尚未本地运行，等PR CI；不得将其记为PASS。实际Lighthouse仍为 `HOST_NOT_RUN`，WorkBuddy V2.2真实导入、网页查询、备份恢复及旧版保护未在主机复验。
- **BSV-B 独立交付** · PR #42 `feature/bsv-b-excel-ingestion` 已交付受控Excel七表字段校验、来源哈希/ID关系检查及差异预览；5项新增测试与本地既有BSV1测试通过，PR CI run `45304293209` 九项通过。状态为 `PREVIEW_ONLY`：Excel→批准签名数据包转换、双人审批与PG事务提交/版本回退未实现，不能导入生产或替代PR #40。
- **交付边界** · PR #40仍未合并，PR #42以PR #40分支为base。两者均未部署；旧版8765/8767、CloudBase、真实订单、员工身份及支付均未触碰。新SHA的完整CI与主机部署结果必须以本记录后续更新为准。
- **CI定向修复** · `cab7b8c` 的首次CI将真实服务角色测试错误设为 `SET SESSION AUTHORIZATION`，并且恢复测试DSN未使用受管端口；已在 `9c8fbfe` 改为真实runtime SCRAM登录和固定端口。该SHA在隔离PG17恢复测试中进一步发现 `pg_restore` 将 `-` 误作为文件名；当前代码改为从stdin读取且不传文件名，等待新CI确认。上述中间SHA存在失败作业，不作为放行证据。
