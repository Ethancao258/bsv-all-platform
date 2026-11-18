# bsv1.store_service｜门店制作与服务

- **企业母版：** `docs/governance/BSV-GOV-ARCH-2026-005_V5.0_20261118.md`
- **业务圈层：** `bsv1`（业务责任归属，不是独立数据库）
- **任务：** 门店自制、收银、调酒、座位、服务、食品安全、闭店
- **相关唯一数据领域：** `production`, `commerce`, `payments`, `service_ops`, `customer`, `quality`
- **真实状态：** `DESIGN_ONLY`，尚未声称此目录下有完成的程序
- **扩展规则：** 二级功能按实际用例增加子目录，并登记到 `config/capability-registry.json`，禁止另造员工/商品/门店主数据。
