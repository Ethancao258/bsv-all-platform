# EdgeOne Makers V13.1 交付

## 构建与健康检查

从本仓库目标 SHA 的干净检出运行 `python3 platform/edgeone/menu/build.py /tmp/bsv-menu-v13.1-preview.zip`，输出必须是尚不存在的路径。发行包只装入 `apps/guest-web/bsv1/site/` 的十个审核公开文件。记录 Git SHA、ZIP SHA 与 `cocktail/data/menu-public.json` SHA。

本地启动 `python3 -m http.server 0 --bind 127.0.0.1 --directory apps/guest-web/bsv1/site`，或者运行 `bash tests/menu-v13-1/check.sh` 自动验证 HTTP。根路径转发 `/cocktail/` 并保留查询串和 hash；以菜单 84 项、同源快照、移动端和选酒单为健康门禁。

## 预览、固定二维码及回退

Makers 项目 ID 与当前域名绑定待只读核验。经授权后，使用独立预览地址测试 ZIP。线上 `menu.bsvm.cn`、`/cocktail/`、`/craft/` 及二维码继续使用当前发布。此包缺少 `/craft/` 源码，**不能替换整个现有项目发布**。生产之前需要获取当前项目的 craft 路由与资源，用预览确认两个路由、真机微信/iOS/Android、缓存及 HTTPS。当前没有创建预览部署。

记录线上现有部署 ID 和公开快照哈希后才可安排审批切换。失败使用 Makers 已核验上一版发布回切，并重查两个入口和商品快照。没有独立部署、生产变更、DNS 变更或数据库迁移。
