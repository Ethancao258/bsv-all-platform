# Codex低消耗启动卡｜R3.2总部地图与既有调酒兼容

**性质：唯一给Codex复制的短指令；完整规则引用仓库内既有文件。** ChatGPT已完成可访问GitHub源码的静态G0预检；先读 `docs/ops/CHATGPT_G0_STATIC_PREFLIGHT_R3_2.md` 和 `contracts/v4-2/G0_EXISTING_ROUTE_FACTS.json`，不要重复做同一份旧源码审计，若实际代码不同才报差异。 **当前未启动Codex、未修改运行代码、未执行测试或部署。**

你是BSV ALL的受限代码执行工程师。基于 `design/v4-2-r3-2-ux-v2-2` 的启动时完整Git SHA创建 `feature/v4-2-g0-hq-layout-bridge`；如SHA/文件不匹配，STOP。先读一次 `AGENTS.md`、`docs/architecture/ADR_R3_2_07_HQ_LAYOUT_AND_CRAFT_BRIDGE.md` 与 `docs/ops/CODEX_R3_2_G0_HQ_LAYOUT_CRAFT_EXECUTION.md`；按实际改动只读取原R3.2其他文档的相关章节，禁止反复全仓扫描和重读全部聊天。

本轮只做以下工作，架构已经固定，不另起应用：
1. 直接复用ChatGPT G0静态报告；只需核对实际HEAD及补齐必要的合成环境/权限/接口运行验证，不重复全仓读码、不再写第二份相同审计；禁止修改真实数据；
2. `/hq`仍为人员审批；`/hq/stores/layout`接回原总部地图编辑器：拖拽、独立店图、图片、草稿、正式发布、历史回滚、新店候选；不得删除原程序/座位ID；
3. 增加identity.A实时HQ授权桥，四动作分别为read/edit/publish/register，不能打开旧SQLite HQ_ADMIN绕过通道，也不能让地图管理员自动获得POS资格；
4. 保留原POS `#guideOverlay`、制作/送达、订单和计时业务内核。未来`/work/craft`只做相同任务的第二视图；本轮只做复用契约与最小保留测试。

**最省使用量的测试策略**：
- 编码时只执行相关**1–3项快速测试**：改路由就测两条URL和越权，改权限就测允许/拒绝/撤权，改地图就测草稿未发布、发布生效及开桌禁止。已有成功测试在代码不变时不重复运行。
- 不要求Codex反复手工运行全套测试或阅读完整通过日志；推送PR后交给GitHub Actions自动运行，并仅输出失败job+简短报错。ChatGPT可以独立审阅PR diff与CI结果。
- 有错误仅修对应模块；连续2次无法定位就STOP并报告，不无限循环重测。
- **申请合并/隔离发布前才检查一次完整PR CI证据，8个既定作业必须全部成功；** 地图、人员权限、订单、审计和主机备份/回退红线绝不能跳过。GitHub CI不是主机实机验收。
- 原业务测试已有同类覆盖时加少量断言，不另外建重复的数套Chromium长测试；HQ只需一条真实拖拽→保存草稿→发布→POS同店读取的浏览器主流程，以及HTTP权限反例。原POS调酒本轮不改内核时一条保留冒烟足够。

**交付**：一个受限代码PR，附变更SHA、原三家地图Git哈希不变、4权限正反例、CI链接和失败摘要、`HOST_NOT_RUN`或真实隔离主机证据、回退路径。禁止自动合并、生产部署、真实CloudBase改表、真钱/短信、给未验证门店发ID。任何无法满足的核心前提标`BLOCKED`，不伪造成功。
