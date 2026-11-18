/**
 * BSV1 顾客菜单 V13.1（V13视觉与推荐规则不变）
 * 此处只允许配置已发布的公开JSON；绝不能填写PostgreSQL、CloudBase、员工/API凭据。
 * DB-A 是服务端逻辑主数据标识，不是浏览器要访问的物理数据库。
 * 未来替换为经授权的公开API时，需同时验证CORS、CSP、HTTPS、数据白名单及备用快照。
 */
window.BSV_MENU_CONFIG=Object.freeze({
  catalogUrl:'./data/menu-public.json',
  fallbackCatalogUrl:null, // 当前单一静态源，无独立灾备；未来API联通后设置经审核的同源快照路径
  catalogTimeoutMs:6000,
  dataSourceAlias:'DB-A-PUBLIC',
  defaultStoreId:'BSVM'
});
