# BSV ALL V4.3｜客户注册和员工认领并入V4.2统一内部阶段

**集成状态：源代码已经合流；待本分支CI及Lighthouse隔离主机实测。正式客户与真实工资结算仍NO-GO。**

## 继承与冲突处理

- 来源PR #20 → PR #24：正式会员网页、员工认领/推广/签名、一次性权益与不可支付佣金候选。源提交 `573a17d9ad4c092f9d3f5ef63559bd987ba2918f`。
- 目标PR #22 → #23 → #25：HQ地图保留草稿、32用例G0和A1网关安全。合流基线 `388a75ef16b5719a19e8d365b8e7ef292fe60a5f`。
- 原PR24的25个文件均作为**新路径**加入，不覆盖统一HQ/POS/身份/菜单源。原根目录README不回滚；在统一工作台与原POS顶部增加明示链接。
- 在既有127.0.0.1:18760私有Ingress以ASGI子应用提供 `/member/`、`/staff/growth/`、`/api/v1/growth/*`；**没有新增公开端口、第二个认证进程、客户正式主库或跨服务自动权限**。
- 员工管理入口使用原identity.A `/api/v1/identity/me` 的Cookie、真实`tr_code/EMP`、legal_entity、按店Grant及`bsv_csrf`；`BSV_GROWTH_TRUST_IDENTITY=1`时拒绝原独立模拟员工登录。会员页面隔离自助注册只关联受控合成身份，非生产微信用户。
- 保留POS订单与座位事实单写源；目前原POS **尚未**签发会员接待HMAC上下文，`/staff/guest-context`没有已授权访问通路；页面不会因此获准读取历史偏好。真正对接须在C/E批实现POS客户关系二次核验后启用。
- 关闭公开Ingress对`/api/v1/growth/internal/*`的转发；真实支付、退款、权益提交、自动计佣付款必须由另行审查的内部可信适配器接通。

## 数据与治理

| 事实 | 原owner | 本次是否新增正式主表 |
| --- | --- | --- |
| Customer/会员/同意 | customer，`customer_id` | 否；仅私有合成 `growth-candidate.sqlite3` |
| TR/EMP/BM、任职、Grant | workforce + identity_access | 否；仅向identity.A同步认证读取 |
| 店铺法人及门店ID | organization | 否；隔离仅BSVT/DEMO_LEGAL |
| POS座位/到店/订单 | commerce / organization | 否；原SQLite仍为当前唯一POS事实源 |
| 触点及客户开发归因 | marketing | 未迁移；隔离候选，不做正式首次开发归属更改 |
| 已核验支付及退款 | payments | 未对接；不产生正式应付佣金 |
| 佣金结算工资 | operating_finance | 未对接；始终 `PROVISIONAL_NOT_PAYABLE` |

公司正式客户永久`customer_id`、原始推荐链和动态服务接待人必须分别维护。纸卡只是提醒，不能凭纸卡兑奖，服务端权益核销依靠经验证支付与订单。佣金比例/逐年系数/归因期继续作为可版本化业务政策，不在本次合流中强制批准6%或365天的新正式规则。

## 运维隔离

- `platform/lighthouse/internal-stage/stage.py`将已有空白`ingress.env`原子升级成隔离配置，若旧文件已有非预期内容一律拒绝；secret放root 0600文件，不进Git。
- 运行时仍为原五个单元（包括postgres），无需增加systemd新组件。既有identity锁定依赖不变，额外安装独立锁定二维码/图片渲染包。Ingress进程文件umask 077。
- 隔离候选SQLite位于`/var/lib/bsv-all-internal-stage/ingress/growth-candidate.sqlite3`；已纳入发布前一致性快照、校验和核对及回退留存。**这只是隔离数据，不可迁往正式Customer主域。**
- 服务验收：私有入口`/member/`、`/staff/growth/`返回页面，`/api/v1/growth/public/config`返回合成设置，未登录员工应401，虚构访客重复注册同一个customer_id；匿名付款内部地址404，未授权门店不暴露偏好。原旧服务8765/8767不变。
- 主机上仍须核查CPU/RSS/磁盘、部署SHA、真正加密备份及恢复、跨店权限撤销、强制关闭调试身份、正式私有/公开入口分界。**仅GitHub CI通过不能标HOST_VERIFIED。**

## 下一项不可跳过的真实集成门禁

1. **组织与身份**：真实员工及第五店、法人映射、合法Marketing Grant及同店排班检查，不可用BSVT合成声明推出生产授权。
2. **客户唯一主档**：CloudBase G0/G1按官方迁移、旧会员去重与隐私保护；禁止将本地测试表create_all到正式PG。
3. **POS访客上下文**：服务端签名120秒令牌且实时二次验证actor、当班、visit、同意、customer关联；仅前端脚本绝不生成凭证。
4. **收入与佣金**：支付机构回调验签、对账与退款事实；归因期/首年全额及长期比例政策快照、离职逐级承接、佣金冲正及独立审计；禁止以模拟收银事实结算工资。
5. **公开客用页**：微信公众平台网页授权域名、HTTPS/ICP备案、隐私政策及同意记录、正确电子菜单域名和有效缓存策略；未验之前保持私有试运行。
6. **真正隔离发布**：上述代码经全部CI通过，负责人明确批准目标SHA后才通过既有bsvctl发布和本机恢复演练；无直连主机工具时必须标HOST_NOT_RUN。

本合流交付解决“各模块在同一代码树、同一个私有网关和身份会话使用”的代码集成，不声称完整 V4.2/R3.2 的32条用例已全部落地。
