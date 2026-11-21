# BSV ALL · 客户会员注册和员工认领网页 V1 · GPT 源码交付

本包可直接合入 `Ethancao258/bsv-all-platform` 现有十四目录下（无新一级目录）。**隔离环境可运行，当前不宣称腾讯云生产部署完成。**

- 顾客：`/member/?store_id=BSVS`，微信 OAuth（须配置真实公众号）或本地测试登录，注册客户唯一 ID、会员状态、返场权益、待确认员工认领。
- 员工：`/staff/growth/`，员工主码核验、签名母版版本保存、个人邀请二维码、门店待认领与申请。
- 后端：`/api/v1/growth/*`，SQLAlchemy 存储、归因证据、微信 OAuth state、CSRF、加密签名母版、候选提成、带HMAC支付事件、一次性权益预占与核销、审计、隐私请求。
- 全部真实财务只进入候选状态 `PROVISIONAL_NOT_PAYABLE`，禁止直接发放。

启动测试：`bash scripts/run_growth_isolated.sh`。测试：`python -m pytest -q tests/customer_growth/test_flow.py`。

项目计划、上线门槛及既有系统对接见 [`docs/architecture/customer-growth/INTEGRATION.md`](docs/architecture/customer-growth/INTEGRATION.md)。上线前必须以真实CloudBase/BSV人员主库与POS实际字段做只读核对，并先在隔离环境中复原测试。
