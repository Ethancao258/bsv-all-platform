# 大量原始数据与旧系统的接入计划（不能提前认定已迁移）

| 来源（待逐项核实） | 原归属 | 目标权威域 | 导入方式 | 关键阻断 |
|---|---|---|---|---|
| CloudBase产品库10表 | 已在现有主库 | catalog / organization | 只读对照+差异修复；不重新灌表 | 映射错列、主键、门店重复 |
| BSV1本地收银/出品程序SQLite及JSON地图 | 门店终端 | commerce/service_ops/organization/event_audit | 旧schema盘点+唯一ID映射 | 支付真实性、历史订单、座位ID稳定 |
| 产品研发与标签Excel | 商品生产 | catalog/production/inventory | 原件哈希+解析+字段类型映射 | 中文名和SKU不可混用、保质期来源 |
| 中央供货督查表A4 | 供货/检查 | production/inventory/quality | 表单结构版本化，人工勾选与机器预填分离 | 实物盘点、人工签收 |
| Service1001/2001/3001教学网页与视频 | 公司知识 | knowledge/learning | 教学URL/源文件权限/版本 + 课程索引 | 未授权第三方版权素材不能直接复刻 |
| 员工入职表/排班/打卡/考级 | HR | workforce/learning/identity_access | 最小必要身份，脱敏映射，逐笔授权 | 个人信息、资质有效期、用工关系 |
| 美团/抖音团购和菜单 | 市场与销售 | marketing/commerce/catalog | 平台ID映射 + 订单核销证据 | 重复计入流水、价格覆盖 |
| 历史会员、返场卡与私域 | 客户关系 | customer | 仅合法来源+明确用途授权 | 未授权数据不得导入 |
| 门店日常财务、SDF及分红 | 日常经营 | operating_finance | 区分直营/合作权属+付款凭证 | 现金收支与净利润不能混同 |
| 咖啡厅等外部合同/扩张计划 | 增长合作 | partnership | 合同条款、业务归属、权限 | 草案不能作为已签约事实 |
| 资本筹划、股权与贷款 | BSV3 | capital | 审议与合同记录，分级授权 | 不把经营备用金作为可投资现金 |

**所有资料先登记来源和真实SHA256，再做字段映射与影子检验。** Git上传脱敏模型/汇总；实际原件存授权私有存储，不把上传资料当作公开代码。
