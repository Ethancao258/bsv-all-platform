# inspector-console｜独立督查工作台

- **功能：** BSV2独立质检、证据登记、整改复核，不得自审自批
- **归属：** bsv2 / 可跨圈层呈现，但不拥有独立主数据。
- **位置：** 仓库 `apps/inspector-console`，非生产服务器真实目录；实际部署见 `config/resource-registry.json`。
- **实施状态：** `DESIGN_ONLY`。旧版本不得未经审计直接覆盖。
- **接口：** 所有动态数据经过 `services/api` 有权限的 API；公开菜单读取审核后的发布快照。
