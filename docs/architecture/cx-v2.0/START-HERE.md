# BSV ALL CX V2.0｜唯一研发入口
DESIGN_HANDOFF_CANDIDATE。正式进入增量研发的设计包，不是已部署软件。先确认当前运行基线，禁止以设计分支或陈旧main覆盖现有POS热升级。
## 开工只读三份
1 本文件；2 ARCHITECTURE.md（共同不变量）；3 WORKPACKAGES/A.md…H.md 本组文件。需要具体字段时按 INDEX.json 查 OPERATIONS/PAYLOAD-SCHEMAS/FEATURE-TRACE；页面按 UI/PAGES.json 查。历史资料仅按需查。
MUST：租户、权限、唯一事实、资金守恒、合法退款、安全及历史版本。RECOMMENDED：本包首选路径。FLEXIBLE：真实代码能更短则自主采用，无需反复审批。腾讯云是共同研发者。共享契约改变须一次协调；局部等效优化直接记录。
总集成人先核查实际运行基线，私下填写 CONFIG/ENVIRONMENT.json 对应证据，分配worktree/owner；不重复盘点。各组独立分支、合成库，按最小业务切片交付。只有生产高风险、跨组冲突等需要审批。
## 优先业务切片
C只读菜单可先；A最小引用与B会员、D返场、E归因候选；F现有POS接单由实机决定；G官方人工先用，获权后自助；H真实收款退款结算在授权后；其他功能独立启用，不等待八组全齐。
## 交付
每组只报 SHA / 完成功能ID及证据 / 测试 / 阻断 / 回退。未授权标BLOCKED_LIVE，继续无资金路径；未运行不得PASS。127操作是候选逻辑合同，不是127个新API。
本轮读取历史源码SHA 2052ef51f011be3c5898d816932d8982f420b752；当前main六个相关文件返回404，当前服务器运行态UNKNOWN。仓库当前公开，任何实际凭据、生产地址、经营政策和客户数据不上传。