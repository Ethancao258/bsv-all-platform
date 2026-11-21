# BSV ALL｜会员注册与员工客户认领 · V2

本功能仅新增既有 `apps/guest-web/member/` 与 `apps/staff-center/growth/`，共享公司身份、门店、客户、订单和事件定义，不新增一级目录，也不替换正在并行开发的POS和身份系统。

- 客户入口 `/member/`：菜单内会员服务，真实身份认证后注册，查询本人权益，自主选择最多两种风味偏好、单独设置是否供当班调酒师查看。**网页不包含任何内部演练/测试文字。**
- 员工入口 `/staff/growth/`：客户接待、门店待认领、个人推广码、签名母版四个页签，适配桌面及手机。先核验所拥有的门店范围，不能默认进入其他门店。
- POS接入：由受信POS生成两分钟以内的本次场次token并调用 `/staff/growth/pos-entry.js`。员工必须获有效点单资格，线上POS身份/门店/班次/客户关联须经后台再次核验后，才会显示用户明确授权分享的风味标签；不允许通过输入客户ID查询隐私。
- 服务API：`services/api/customer_growth/app.py`。数据库依旧是隔离候选模型，生产CloudBase迁移尚需G0只读结构核对、G1备份恢复、权限及官方迁移审核。既有模拟POS结算不能产生可支付工资，所有佣金仍 `PROVISIONAL_NOT_PAYABLE`。
- 真实微信OAuth：只接受公众号 `snsapi_base` 标识，不自动取得昵称或手机号。微信运营方AppID/密钥、网页授权域名、HTTPS回调待配置；短信、支付宝与小程序登录没有假装已实现。

本模块在本独立分支的源文件与配置，参阅 [`docs/architecture/customer-growth/INTEGRATION_V2.md`](docs/architecture/customer-growth/INTEGRATION_V2.md) 和 [`config/modules/customer-growth-v2.json`](config/modules/customer-growth-v2.json)。

本地隔离回归：`python -m pytest -q tests/customer_growth/test_flow.py tests/customer_growth/test_service_preferences.py`；前端脚本语法：`node --check apps/guest-web/member/app.js`、`node --check apps/staff-center/growth/app.js`。生产部署必须经过授权、备份验证、真实支付对账及数据权限门禁。
