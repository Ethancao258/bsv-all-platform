# BSV ALL｜跨AI协作、变更路由与持续交付控制面 V1.0（设计契约）
> 创建于2026-11-20。状态：**DESIGN_APPROVED_FOR_IMPLEMENTATION / NOT_YET_DEPLOYED**。本文件是Codex的可执行工程规格，不声称以下拟议控制器、命令、自动触发器已部署。沿用 `AGENTS.md`、14根目录冻结、`config/data-ownership.json`、`config/resource-registry.json`、`docs/architecture/DEPLOYMENT_BOUNDARY.md`。工程任务：Issue #9。任何生产发布仍需独立风险审批。

## 0. 统一目标、已知事实与实施边界
经营负责人希望只用一句自然语言描述需求，系统能找到唯一负责模块，向Codex下发精确变更，在GitHub审查并测试，部署到已有腾讯云北京Lighthouse，验收后返回一个固定的网址和结果；之后可以随时改页面、业务规则或数据源位置，而无需重新解释整个系统。

**已核实（用户终端与浏览器证据）：** PR #8测试程序的已部署SHA `13dad3df84eacd83ffd9ddc8112cbcee6c3256ec`；Lighthouse Ubuntu 24.04，4核约4GB/40GB；旧 `bsv1-preview.service:8765`、`bsv-all-bsv1-stage.service:8767` 均active，新 `bsv-all-internal-stage@postgres/identity/pos/supply/ingress` 在localhost:18764/18761/18762/18763/18760均active；Windows SSH隧道打开入口、合成TR/EMP/BM登录、总部查询TRA0002、隔离POS旧码映射只读预检和**唯一合成旧码提交及再验证**均通过。仅隔离数据。中央D/E真实写入、CloudBase生产、真实收款、正式HTTPS入口均未就绪。

**V1/V2/V3关系**：Issue #9最初V1为隔离集成测试业务闭环；V2叠加文件所有权、人本位UI及批量E2E；本V3在**同一个任务**中增加可持续交付和自动变更路由，V3替代旧提示词，不意味着先执行V1/V2两轮。不得借V3长期规划挤占本轮P0业务验收。

## 1. 长期唯一工程事实源
| 事实 | 唯一登记位置 | 消费者 |
| --- | --- | --- |
| 业务圈层BSV1/2/3及权威主数据归属 | `AGENTS.md`、`config/data-ownership.json`、治理V5文档 | 所有Agent |
| 自然语言变更属于哪个模块/代码/API/测试/运行服务 | **`config/change-routing.json`**（本次新增索引，只作路由，不代替原有owner配置） | ChatGPT/Codex/验收器 |
| 数据源别名与替代方案 | `config/modules/identity-data-sources.json`、`config/modules/supply-sources.example.json` | 对应模块配置加载器 |
| 凭据/实际端点/高风险URL | **Lighthouse受限配置或授权密钥服务（不得提交Git）** | 运行服务 |
| 源码与可审计历史 | GitHub私有仓库、PR、review、CI、不可变commit SHA | Codex与部署器 |
| 当前主机/数据库/发布证据 | `docs/ops/CURRENT_STATE.md` + 服务器本地只读验收报告 | ChatGPT/Codex/负责人 |
| 发布候选审批与回退依据 | 拟议 `release-manifest.json` + 本机被授权的批准记录（尚待实现） | Lighthouse部署器 |

不要把ChatGPT对话、Codex的临时工作目录、运行中的systemd文件或源代码主分支视作另一份相互冲突的事实源。要区分 `repo_head_sha`、`approved_release_sha`、`deployed_sha`、`database_schema_revision`、`config_revision`。

## 2. 模块定位与变更任务契约（必须机器可读）
收到“把总部授权文字改成人话”“数据库A换服务器”“调酒POS调整开桌”等语言时，ChatGPT首先读取`config/change-routing.json`，将请求归类为单一或多个`module_id`。路由由明确字段匹配而非猜想：
- `scope`=UI_COPY / UI_FLOW / API_LOGIC / SECURITY_GRANT / SOURCE_ENDPOINT / SCHEMA_MIGRATION / OPERATIONS / HARDWARE。
- `target_environment`=isolated / staging / production；未明确时默认isolated，不自动扩大生产范围。
- 每个变更请求有 `request_id`（如`BSV-CHG-YYYYMMDD-xxxx`，由系统生成，不是人员/商品永久码）、用户要达成的**可观察行为**、`module_ids`、`paths`、`source_namespace`、`known_state`、`non_goals`、`test_positive`、`test_negative`、`revert_gate`、`approval`。
- 人类仍可用自然语言，无需手写JSON。Codex必须将上述字段落在PR/Issue，任何不确定的权限或数据库主从切换先停在REVIEW而不是自行补猜。
- 一个路径只允许一个开发写入负责人；可以分包并行，但集成签名由唯一Reviewer收口。任何合并只审查变化和测试，不重写现有14根目录。

**示例机器请求（仅示意格式）**
```json
{
  "request_id": "BSV-CHG-20261120-0001",
  "user_intent": "总部授权页用中国员工看得懂的中文说明",
  "module_ids": ["identity-hq-ui"],
  "scope": "UI_COPY",
  "target_environment": "isolated",
  "non_goals": ["改变服务端grant规则", "连接生产CloudBase"],
  "test_positive": ["HQ表单提示就地显示", "现有API状态码和权限拒绝不变"],
  "test_negative": ["无权限角色不能操作授权", "提交超时不虚报已成功"],
  "approval": "staging-only"
}
```

## 3. 跨模块数据源：**必须使用完整命名空间**
身份模块的 `A/B/LOCAL` 与供货模块的 `A–G` **并非相同含义**。全局变更路由必须使用 `identity.A` / `identity.B` / `identity.LOCAL` 及 `supply.A` ... `supply.G`，禁止一句“修改A库”未经确认就写入两个系统。
- 身份 `identity.A` 是当前隔离PG权威可写身份事实；`identity.B`仅可选非敏感只读参考；`identity.LOCAL` 是加密备份，不能充当实时授权源。
- 供货 `supply.A` 商品物料，`B` 身份接口，`C` 门店/库位，`D` 中央库存配送权威账本，`E` 独立督查事件，`F` 视觉识别候选，`G` 事件通知。当前仅`supply.B`在内部测试以localhost配置，其他正式权威源未接入。
- POS隔离订单目前使用SQLite，本地员工别名通过统一身份授权接口鉴权；**本地订单SQLite不能被假称为集团财务/订单权威主库**。
- 改动位置应是由运行时配置解析的`logical_source_id→primary_endpoint/standby_read_endpoint/credential_ref/allowed_operations`，从**可版本化的逻辑路由**到受控运行环境注入**真实URL和凭据**；禁止在前端或业务方法硬编码PG连接串，禁止把密钥放GitHub。
- 数据库位置变动先比对真实schema版本/主键/权限/迁移账本，再做只读连通、原库备份+隔离恢复、目标复制与一致性核对、切换决策及回退。涉及数据库**权威写源**更换必须另走ADR和停写/双写/CDC一致性方案，默认不得自动切换。
- 读取故障：仅非敏感静态信息可读已批准的限龄备份；人员授权、审批、订单支付、库存账本写入全部fail-closed，绝不因为CloudBase无法访问便切换本地旧快照授权或假称提交成功。
- 任何“替换URL/主备配置”至少检验DNS/TLS、最小权限、schema与契约、超时/重试、凭据轮换、数据一致性和回退触发条件。正式生产主库不因一句话迁移。

## 4. 交付链路：短期与最终两条，不假装已经打通
**短期（本轮必须可用）：**
`ChatGPT从变更路由生成Issue/PR要求 → 用户在Codex会话发出指令（当前无已授权Codex直调工具）→ Codex提交GitHub PR+CI → ChatGPT审查+负责人批准不可变SHA → Lighthouse一条本地前台部署命令 → 批量E2E → 输出服务器及PR的版本信息`。
这是一条**一次命令部署链**，但并非“单句无人值守发布”。在现有工具授权下，ChatGPT可以直接更新GitHub，尚不能直接SSH控制Lighthouse或从此处自动开启Codex会话；不能声称后两项已链接。

**中期（独立实现并经过许可后）：**
创建最小权限受控“部署控制器”（拟议`platform/lighthouse/internal-stage/bsvctl.py`），在本机根据批准的40位commit SHA从只读Deploy Key拉取特定代码，核对源SHA、已批准CI和release manifest，再运行 `stage.py` 的预检、备份、原子版本切换、真实健康+业务验收和回退，生成带SHA的结果。首次配置/安装仍需负责人授权。
推荐命令接口（**建议接口，当前未实现**）：
`bsvctl status`、`bsvctl deploy --env isolated --sha <40位SHA>`、`bsvctl verify --env isolated`、`bsvctl rollback --env isolated`。
不能执行任意Github Issue文本、任意Shell或未批准PR代码；仅已通过受控审批的SHA可部署。长耗时可交systemd瞬态任务并回报任务ID，普通操作前台可见。

**长期（只有连接器和服务器控制面真实授权后）：**
在ChatGPT和Codex具备对应写权限/受控触发器时，用`request_id`从Issue触发编程任务，用带作用域的审批事件发布已冻结的release manifest，再由Lighthouse轮询**明确批准**的发布队列或使用受控TAT/部署API执行。可实现“用户一句话提出变更→自动开发与测试→等待生产批准”，但**不等于用户一句话就能绕过审批/任意生产迁移**。
- **不在这台4GB服务器上部署可运行任意PR代码的GitHub self-hosted runner**。GitHub安全指南明确警示私有仓库中可提PR的参与者仍可能获得runner运行权限或泄露token。优先GitHub托管CI + Lighthouse只读拉取受控发布。
- `workflow_dispatch`等触发只在所需GitHub连接/权限及工作流配置真实可用后启用，不能凭工作流YAML存在就称已连接。独立审批记录不得仅依赖账号订阅可能没有的GitHub environment protection。

## 5. 发布构件与审批门槛
每个候选版本须有**机器可验证**的`release_manifest`，字段至少：
`request_id, module_ids, repo_head_sha, proposed_release_sha, ci_run_url, ci_conclusion, migration_ids, config_revision_hash, artifact_digest, resource_preflight, expected_units, rollout_environment, backup_snapshot_ref, rollback_target_sha, acceptance_report_ref, approval_actor, approval_timestamp, deployed_sha, host_verification, no_payment, no_prod_db`。
- 机密只能用不可反推引用ID，不写JWT、PIN、PG密码、CloudBase密钥、明文日志或客户资料。
- `CHECKS`：源码/分支/SHA不可变、CI全部P0通过、脚本语法、端口/资源/目录预检、旧服务健康、数据库迁移账本/备份、无异常公网绑定。
- `GATE`：仅UI文案且无权限/数据库变更可在isolated获批快速发布；权限、业务交易写入、数据源、schema、真实支付需更严格人工确认；生产接入必须安全审计、真实备份恢复和合法运营审批。
- `ROLLOUT`：尽量按module部署但不得在代码和数据库schema不兼容时做半套灰度；有共享接口改动要先跑契约回归，再统一更新。服务器已有旧8765/8767永不受本次发布脚本重启。
- `ACCEPT`：内网HTTP实测、至少正反权限用例、订单仅未付款、数据库写前后审计；输出 `STAGING_ACCEPTED` 或 `STAGING_BLOCKED`，细分PASS/BLOCKED/MOCK_ONLY/NOT_RUN。任何未确认写入不能显示已成功。
- `ROLLBACK`：失败恢复上版源代码与已验证服务配置；**数据库向后不兼容更改不能仅切Symlink当作完成回退**，必须独立恢复测试和迁移方案。
- **服务器资源约束**：4核约4GB/40GB运行旧两套+新五单元，无证据表明可承载生产五店高峰。增加服务前采集内存、CPU、磁盘、PG连接数、HTTP P95及备份耗时基线；进程异常/内存不足/磁盘水位预警应阻断发布，具体阈值在主机采样后批准，不臆造容量或成功率。

## 6. 人本位产品规则（持续适用）
- 一线员工看中文动作与后果，管理者看职责与待办，不必理解`A库/PG/JWT`、`reviewed/ALREADY_MAPPED`等技术词才能完成操作。
- 一次点击后的状态必须明确`尚未提交/执行中/已确认保存/失败未保存/结果未确认`。网络断开时**不擅自说“操作已中止”**：请求可能已被服务端执行，应查idempotency key或审计记录后再重试。
- 前端用业务友好的中文，后台稳定机器错误码、关联request ID、审计字段保留；错误就地显示，状态公告满足键盘及移动屏幕访问。
- 入口以角色分组：员工、当班负责人、总部、独立督查。各模块必须展示`可操作/仅查看/暂未开放`，不可因服务healthy就显示“可经营”。手机号/支付/客户资料不得进入合成staging。
- 界面美学使用已批准的BSV暖白/深棕/哑金系统，不能为装饰牺牲对比度和可读性；375px移动与桌面均需验收。

## 7. 变更分类与安全处置
| 请求类型 | 一句用户指令样例 | 开发路由 | 必须额外确认 |
|---|---|---|---|
| UI_COPY | “把权限展示改成中国店员能看懂的话” | `identity-hq-ui` | 文案保留审计含义与权限边界 |
| API_LOGIC | “顺义POS只能由授权店员开桌” | `store-pos` + `identity-api` | 真实门店岗位、负例测试 |
| SOURCE_ENDPOINT | “供货B源换一个地址” | `supply-api` + `deployment-config` | 明确supply.B、TLS、密钥/只读范围、回退 |
| SCHEMA_MIGRATION | “把集团人员表迁到其他PG” | `identity-api` + `deployment-config` | 生产变更单、G0/G1、完整恢复证明、唯一写源 |
| OPS | “部署刚批准的隔离版本” | `deployment-config` | SHA、CI、备份、回退 |
| HARDWARE | “标签打印机连统一标签系统” | `device-label` | HPRT T260L 203dpi/50x40mm与本地控制边界 |
| MARKETING/MENU | “修改电子菜单文字” | `guest-menu` | 真实公开资源、V13源、EdgeOne审批，不上传涉密数据 |

## 8. 任务状态机与交接验收
`REQUESTED → ROUTED → CODEX_STARTED → PR_READY → CI_PASSED → REVIEW_APPROVED → RELEASE_APPROVED → DEPLOYING → HOST_VERIFIED → STAGING_ACCEPTED`；遇错误转`BLOCKED`，触发安全回退后转`ROLLED_BACK`，**生产上线为另一个批准状态**。
- 状态必须由对应系统真实证据提升，不能根据“写了PR”“CI绿”“CodeX说完成”跨越`HOST_VERIFIED`。
- 服务器只有read-only Git deploy key，不能自动回写GitHub状态；目前用户可复制审计报告，ChatGPT经GitHub工具归档。将来如建立回传服务，使用最小权限且只推送脱敏状态，绝不让服务器私钥拥有GitHub通用写权限。
- 一次性交付最小包：可用PR、精确SHA、无凭据的`DEPLOY_COMMAND`、`ACCEPT_COMMAND`、`ROLLBACK_COMMAND`、`CURRENT_STATE`、变更路径及所有阻断项。Codex必须证明其本地CI与主机验收的区别。
- 本轮编码P0先把`Issue #9`原有的隔离身份→POS未付款订单闭环、中文UI、E2E、可重复发布完成，再实现**最小**`bsvctl`包装器和变更路由校验。生产持续监控/无人值守自动部署/多数据库迁移是后续P1，**不能抢占今日隔离测试版交付**。

## 9. 强制反例与完成定义
- ChatGPT未授权直接操控Lighthouse或启动Codex时，一句话只会变成Issue/工作指令，**不能声称服务器已经改好**。
- 若更改`identity.A`、`supply.A`、CloudBase主库，必须分辨数据归属和环境，碰正式源时强制审批；没有完整回退时标记`NO_GO`。
- 若GitHub 7/7 CI通过，但Windows实际按钮静默、POS未付款闭环未过、或新服务未运行，仍是`STAGING_BLOCKED`。
- 若新菜单UI好看却让人误认为已连接真实库存/收款，属于发布错误。
- 只有系统经过真实浏览器和Lighthouse批量E2E且旧服务无回归，才允许给出`STAGING_ACCEPTED`；生产上线要另证据。
