# ChatGPT先行G0只读预检｜BSV ALL R3.2

**审计时间**：2026-11-21。**证据级别**：GitHub源文件比对＋对实际JSON/源码内容执行静态断言（由ChatGPT调用GitHub连接器后，在工具中运行JS），**不是Python单元测试、真实浏览器测试、主机HTTP或Lighthouse验收**。此报告可替代Codex对本部分的重复静态研究。源码基线SHA：`c51b58d67dabae53afcdf9851a80cdc93d4200f6`。当前设计分支：`design/v4-2-r3-2-ux-v2-2`，只有docs/contracts新增，不含运行代码修改。

## 1. 已检查且通过的静态事实

| 项目 | 结果 | 直接证据 |
| --- | --- | --- |
| V4.1→R3.2设计分支旧代码 | 340/340原Git blob SHA相同；未修改/删除旧代码和地图；只新加设计与契约文件 | Git树对象哈希对比 |
| 密云BSVM地图 | 13个座位节点、ID无内部重复、邻接引用都存在 | `services/api/bsv1/store_layouts/BSVM.json` |
| 顺义BSVS地图 | 13个座位节点、ID无内部重复、邻接引用都存在 | `services/api/bsv1/store_layouts/BSVS.json` |
| 通州BSVT地图 | 17个座位节点、ID无内部重复、邻接引用都存在 | `services/api/bsv1/store_layouts/BSVT.json` |
| 全三店座位ID | 43个节点、跨店重复ID为0 | 三份JSON解析后set检验 |
| 富民街BSVF | stores.json中存在，layout_file=null；不得借其他店图 | `services/api/bsv1/store_layouts/stores.json` |
| HQ拖拽保存/发布/历史回滚 | `draft/publish/rollback_to`原业务函数存在 | `services/api/bsv1/bsv_one.py` |
| POS内嵌调酒引导 | `openRecipeGuide/guideStartTimer/guideFinishConfirm/guideDeliverConfirm`存在 | `apps/store-console/bsv1/app.js` |
| GitHub完整CI配置 | 有8个必需作业；`push`与`pull_request`均触发（可能重复） | `.github/workflows/validate.yml` |
| 设计内容 | PR #15/#16保留多应用、多地图、双审批和唯一owner；PR #16仍Draft | GitHub PR metadata |

## 2. 已证明但还需Codex修复的代码事实

**B-01【路由】**：`platform/lighthouse/internal-stage/ingress.py`将`/hq`送identity人员审批；POS旧`/hq`也为总部地图编辑器。目前不存在可用且经过身份鉴权的新路径`/hq/stores/layout`。必须按ADR加路由，不删任一页面。

**B-02【实际权限】**：`services/api/bsv1/app.py`在V4的device-required/identity-required条件下显式拒绝`/api/hq/*`；`bsv_one.py`旧HQ依赖`bsv_hq_roles/HQ_ADMIN`本地授权。不能简单取消403；必须实现集团identity.A实时鉴权与read/edit/publish/store.register最小粒度授权。

**B-03【会话】**：旧`apps/hq-console/bsv1/hq.js`在初始化时调用`/api/state`并用旧POS `X-BSV-CSRF`；不能要求总部BM为了编辑地图先成为本店设备当班员工。按ADR采用身份会话绑定CSRF，单独验证Origin、scope和actor，未知则拒绝。

**B-04【新店副作用】**：旧`bsv_one.create_store()`会`INSERT INTO staff_store_access`。集团HQ新店注册**不能因为地图编辑权限给本人添加POS门店资格**。Codex需用受控新增路径复用原布局业务但消除这条V4副作用；保持legacy老路径在原受限测试环境的既定行为。

**B-05【调酒重建风险】**：旧POS已拥有完整`guideOverlay`及本地production任务。未来`/work/craft`只能作为受限第二视图；本阶段不重建调酒业务内核。

**B-06【公开菜单】**：现有`ingress.internal_menu()`对匿名`/cocktail/`注入“返回工作台”，且根据未受信的`?from=pos`显示“返回点单台”，仅是UI链接并不授予POS权限，但会混淆顾客入口。应取消匿名内部导航，仅对有真实受权会话提供安全内部导航。

**B-07【旧地图可访问性】**：不能以“函数和HTML存在”宣称当前V4集成入口可运行；必须由后续合成E2E/浏览器实测确认。

## 3. 本轮不需要Codex重复完成的工作

- 不重复阅读旧聊天去重新发现R3.2要求；已经在Issue #14、PR #15、PR #16中。
- 不重复发明二十个领域的owner、三店地图或新店码；已有公司注册表及source facts。
- 不重复从头研究旧HQ路由/鉴权原因；B-01到B-04已有直接源码证据。
- 不要求Codex反复手工运行8个完整CI作业；由PR的GitHub Actions执行，Codex仅跑当前改动对应1–3个快速测试并查看失败摘要。

## 4. 尚不能由ChatGPT在本连接内完成的内容

| 待完成 | 原因 | 应交由 |
| --- | --- | --- |
| 真正修改Ingress/identity/POS HQ桥及原页面 | 涉及多文件依赖、数据库约束和运行时验证 | Codex，在受限PR中 |
| 启动合成PG＋SQLite、运行HTTP/Chromium身份回归与地图发布流程 | ChatGPT当前未取得完整可执行的项目环境，不能把源码静态核查当服务端测试 | GitHub CI；失败由Codex定向修复 |
| 真实CloudBase schema/业务法人第五店核查 | 本次没有具备相应官方数据源或授权证据 | 后续获批准时专项取证，未知先BLOCK |
| 腾讯云隔离主机真正的部署、回退、恢复 | 本轮无主机SSH授权，生产仍NO_GO | 负责人显式批准SHA后的受控运行 |
| 功能完整性实机签字 | 用户实际手机、Windows与门店环境有交互条件 | CI＋最后人工验收 |

**此报告不是G0全部完成**：只是将可从GitHub直接完成的静态部分先行解决。Codex不得重新研究本报告已确认的事实，但必须对自己将要修改的接口做简短受控源码确认，遇到真实冲突则BLOCK并附证据。
