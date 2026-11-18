# 平台基础设施与部署目标

- `cloudbase/`：现有托管业务数据/认证环境配置及运行元数据，涉及数据库 schema 的正式迁移只能在根目录 `cloudbase/migrations/`。
- `lighthouse/`：北京Ubuntu实际主机、systemd、reverse-proxy、端口、备份、进程版本；未盘点前保留原七大服务根目录。
- `edgeone/`：Makers电子菜单的发布和域名配置；保留 `menu.bsvm.cn` 路径。
- `security/`：凭据生命周期、密钥轮换及审计，Git不保存密钥。
- `observability/`：错误指标、告警、容量、恢复演练和部署记录。

**平台迁移不应迫使业务域和API契约改名。**
