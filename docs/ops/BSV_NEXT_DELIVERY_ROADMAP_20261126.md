# BSV ALL｜后续交付预建总路线（2026-11-26）
> 状态：PREPARED_ONLY；规划/执行卡已创建，**未开始新模块研发**。本路线不覆盖/解冻 [#44](https://github.com/Ethancao258/bsv-all-platform/issues/44)，不批准生产部署。前置基线：`main@e2a0368bb89d30627c5eae9be062cae38f82760d`。此计划为2026-11-26的预备快照，后续实时状态看Issue与实际Git/主机证据。

## 0. 交付链而非审计循环
`#44 A/B冻结交接 → #44 C唯一集成与M1实际候选/经批准发布 → 按依赖启用下一个已预建Issue → 腾讯云唯一Agent编码→PR/CI→隔离浏览器验收→发布审核→停止/交接`

- 当前**不启动**#45-#56；#44优先级高于旧#43的「继续R07」说明。
- 每个新Issue的正文已经包括**权威代码位置 / 已有成果 / 三步执行 / 验收 / 停止点**。腾讯云只需要一个Issue URL和开工授权，无需长提示词。
- 若#44未确认A、B各自冻结且停写，C也不得写入集成；若C尚未发布M1，后续业务执行卡默认不开放。
- 主线采用**WIP 1个共享写入人**。独立文件/独立服务/纯测试可并行，但有共享`app.py`、人员/商品/订单数据模型或发布服务写入时串行归属。优先切换到下一张已可执行卡，不新增一次全面摸排。
- 「已完成代码」≠「测试通过」≠「隔离网页可用」≠「正式发布」；缺生产权限不绕过，允许生成可复现冻结候选。
- 不上传真实员工/会员/交易/商品敏感明细、审批密钥、内网日志或数据库。只传去敏证据、Git SHA、契约逻辑名、受控包引用。遵循仓库`AGENTS.md`和`config/data-ownership.json`；十四个根目录不变。

## 1. 当前门禁：现有工单，不重建
| 门禁 | 原始依据 | 真正停止条件 |
|---|---|---|
| F0 A/B成果冻结 | [#44](https://github.com/Ethancao258/bsv-all-platform/issues/44) | 两Agent各有完整Git SHA/可复现交付/阻断摘要，且已停写；`READY_FOR_INTEGRATION` 或 `FROZEN_BLOCKED` |
| F1 C第三方首店M1 | [#44](https://github.com/Ethancao258/bsv-all-platform/issues/44)、[#43](https://github.com/Ethancao258/bsv-all-platform/issues/43) | R06商品、登录、开桌、出品、收款登记及离店、历史/日报完成隔离网页验收；生产授权后才可`M1_RELEASED`。否则`READY_FOR_RELEASE_APPROVAL`或`RELEASE_BLOCKED`，立即停止 |
| 旧版商品/权限/集成资料 | [#41](https://github.com/Ethancao258/bsv-all-platform/issues/41)、[#14](https://github.com/Ethancao258/bsv-all-platform/issues/14)、[#37](https://github.com/Ethancao258/bsv-all-platform/issues/37)、PR #40/#38/#36 | 只继承经核验已实现项；不将旧设计或者模拟数据写成生产事实 |

## 2. 预建执行卡及依赖（不等于今天开工）
| 波次/编号 | 工作流程 | 已建Issue | 业务验收目标 | 启动依赖 |
|---|---|---|---|---|
| 1 / R07 | 调酒引导/制作/出品 | [#45](https://github.com/Ethancao258/bsv-all-platform/issues/45) | 员工从订单进入正确批准配方并完成出品 | #44 C候选稳定；已有配方事实 |
| 1 / HQ01 | Excel商品维护、审批/发布与POS同步 | [#50](https://github.com/Ethancao258/bsv-all-platform/issues/50) | 总部批准新版后POS可用，未批准不可售 | #44 B冻结、#41/PR40复用；审批授权 |
| 1 / OPS01 | GitHub→腾讯云部署、备份及逐店发布 | [#55](https://github.com/Ethancao258/bsv-all-platform/issues/55) | 定版SHA发布、回滚/重启实测，阶段化门店上线 | #44 C最终发布/阻断结果、现有OPS-002/003 |
| 1 / R09 | 学院门店资格、临时人员、排班、撤权 | [#47](https://github.com/Ethancao258/bsv-all-platform/issues/47) | 经培训并在班次员工才取得指定门店操作 | #44 C身份界面稳定、#14/#37复用 |
| 2 / R08 | 公告、任务、日会和日报 | [#46](https://github.com/Ethancao258/bsv-all-platform/issues/46) | 管理端发布到员工反馈闭环 | #47稳定身份/受众契约 |
| 2 / R10 | 免费会员、客户归因、佣金及权益 | [#48](https://github.com/Ethancao258/bsv-all-platform/issues/48) | 真实支付订单→客户认领/可追溯权益佣金 | #44 C有效订单、#47身份 |
| 2 / R11 | 自动支付、退款与对账 | [#49](https://github.com/Ethancao258/bsv-all-platform/issues/49) | 支付机构实际确认与人工登记严格分离 | #44 C人工收款、商户准入/独立授权 |
| 2 / SUP01 | 中央预制、批次、库存及标签 | [#52](https://github.com/Ethancao258/bsv-all-platform/issues/52) | 一笔配方→批次→配送→签收→库存追溯 | #50商品/物料批准、现有供货服务 |
| 3 / GUEST01 | 电子菜单、扫码点单与核券 | [#51](https://github.com/Ethancao258/bsv-all-platform/issues/51) | 顾客桌台单进入同一POS订单事实 | #44 C订单、#50菜单；外部核券须接入授权 |
| 3 / CX01 | 客诉反馈、回访、质量闭环 | [#53](https://github.com/Ethancao258/bsv-all-platform/issues/53) | 客诉从接收至处理/复核/关闭 | #44 A成果、#48客户授权/身份 |
| 3 / FIN01 | 多店日报、SDF、利润与异常 | [#54](https://github.com/Ethancao258/bsv-all-platform/issues/54) | 可与真实流水核对的门店日报与差异 | #44 C真实收款、成本/采购事实；自动渠道可后接 |
| 3 / HR01 | 合同、纸本寄送、签署归档与离职 | [#56](https://github.com/Ethancao258/bsv-all-platform/issues/56) | 从模板到总部收件验收、档案与交接 | #47员工权威身份、受控文档存储 |

**备注**：波次不是强制串行日期；满足前置且文件owner不冲突即可并行。若同一Issue所述能力已由现有PR真实交付，先验收、标记`ALREADY_IMPLEMENTED`，**不要重写**。如业务优先级有变化，由总控更新本表和Issue启动顺序，不扩大当前写入权限。

## 3. 腾讯云 AI 一次一个任务的固定执行过程
1. **读**：`AGENTS.md`、本卡正文、#44当前交接结论、卡中列出的代码文件；只读取当前工作的最小范围。辨认实际运行服务和Git工作树，先检查是否已有同等实现。无必要不新建架构。
2. **做**：一个独立worktree+分支，声明唯一文件owner；按本卡三步实现可用的最小业务闭环；只做定向测试、实机隔离浏览器验收；出现新阻断最多两次不同修复尝试后冻结交接，避免反复摸排。
3. **交**：完整`BASE_SHA`、`HEAD_SHA`、PR、影响文件、复现命令、实际URL/验收、未完成项、回滚、下一单；更新本卡状态，停止写入。生产切换需要额外明确授权；代码/CI通过不算上线。

**最短调用语**：`执行 <GitHub Issue URL>。按工单三步实现，沿用现有代码；提交PR、Git SHA、网页验收和停止状态，完成即停止。不得擅自扩大范围或越过#44。`

## 4. 验收及状态规则
- `PREPARED_NOT_STARTED`：任务已预建，未开工。不能计入上线完成率。
- `READY`：前置条件和写入人已确认，由经营负责人启动。
- `IN_PROGRESS`、`TESTED`、`STAGED_VERIFIED`：分别为代码、定向测试、候选网页实测；不等于`RELEASED`。
- `BLOCKED`：写清唯一阻断及申请动作；不追加无关研究。
- `FROZEN / READY_FOR_RELEASE_APPROVAL / RELEASED`：代码停写；生产发布只依据特定SHA批准及回退验证。
- 在公开GitHub仅记逻辑名和匿名化测试证据，实际资源私有标识/密钥不得外泄。

## 5. 总控升级规则
- 腾讯云Agent只执行已经`READY`的单个Issue，不接受「发现新想法便自行开新项目」。
- 两次有区别的尝试仍失败，写BLOCKED并交由项目管理决策，不复读检查。
- 某卡完成后，项目经理先确认验收与状态，按依赖激活下一张；首店M1后**可以**开后续工单，但不能由#44 C自行连跑。
- 业务底线：不丢单、不漏款、不错误放行禁售商品、不跨店越权、不把演示当真实经营、不破坏现有客户/财务记录。
