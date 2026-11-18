/* [CLOUD_ENTRY] 预览链接可能带有临时查询参数（如 eo_token）。
   从项目根地址进入 /cocktail/ 时保留全部查询参数，以免出现预览 401。
   本文件不含商品/价格数据，不调用其他系统。*/
(() => {
  'use strict';
  const target = new URL('./cocktail/', window.location.href);
  target.search = window.location.search;
  target.hash = window.location.hash;
  window.location.replace(target.href);
})();
