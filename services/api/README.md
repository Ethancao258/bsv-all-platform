# api

唯一授权API层，按业务域调用，查询服务不能公开内部资料；新业务先加二级模块，不能另建第二个统一API。

尚未建立可运行的服务。

## 本地测试预览

从工程根目录运行 `python3 services/api/preview.py`。菜单位于 `http://127.0.0.1:8765/`，门店点单演练位于 `/store/`，只读 `GET /api/v1/menu` 返回同一份合成菜单快照。草稿只存在于当前浏览器页面。正式 API 仍待实现。

## 真实 BSV1 交接程序

`services/api/bsv1/app.py` 为 V3.1 私有验收入口。使用 Python 3.12 标准库，显式提供隔离的 `BSV_DB_PATH`、经批准工作簿路径 `BSV_V9_XLSX` 及独立 `BSV_PORT` 后启动。干净检出可用 `bash tests/bsv1/check.sh` 与 `bash platform/lighthouse/bsv1/release.sh --simulate` 自行生成合成工作簿、验证功能、检查实际启动。生产工作簿通过受控渠道提供。
