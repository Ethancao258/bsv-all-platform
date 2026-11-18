# store-console｜BSV1门店操作端

- **功能：** BSV1座位地图、待下单与结算、调酒引导、制作/送达、保洁、开闭店、离线同步；班次任务
- **归属：** bsv1 / 可跨圈层呈现，但不拥有独立主数据。
- **位置：** 仓库 `apps/store-console`，非生产服务器真实目录；实际部署见 `config/resource-registry.json`。
- **实施状态：** `DESIGN_ONLY`。旧版本不得未经审计直接覆盖。
- **接口：** 所有动态数据经过 `services/api` 有权限的 API；公开菜单读取审核后的发布快照。
