-- BSV ALL｜中央 PostgreSQL schema 设计提案，禁止直接运行生产环境。
-- 表名全部为逻辑提案；必须先与现有公司库核对，复用主表及主键。
-- 不创建产品、门店、人事副本。实际 FK 请引用主库已批准的正式表。
CREATE SCHEMA IF NOT EXISTS supply;
CREATE TABLE IF NOT EXISTS supply.shipment (
  shipment_id uuid PRIMARY KEY,
  source_location_id text NOT NULL,
  dest_location_id text NOT NULL,
  state text NOT NULL CHECK(state IN ('DRAFT','READY','DISPATCHED','PARTIAL_RECEIVED','RECEIVED','DISPUTED','CLOSED','CANCELLED')),
  version integer NOT NULL DEFAULT 1 CHECK(version>=1),
  created_by_employee_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (source_location_id<>dest_location_id)
);
CREATE TABLE IF NOT EXISTS supply.shipment_package (
  package_id uuid PRIMARY KEY,
  shipment_id uuid NOT NULL REFERENCES supply.shipment(shipment_id),
  item_id text NOT NULL, -- FK 到公司产品主数据；此处不复制主表
  lot_id text NOT NULL,  -- 参考公司批次身份；接入审核后加 FK
  base_uom text NOT NULL,
  qty_base numeric(18,4) NOT NULL CHECK(qty_base>0),
  state text NOT NULL CHECK(state IN ('DRAFT','READY','IN_TRANSIT','ACCEPTED','HOLD','RETURNED','SCRAPPED'))
);
CREATE INDEX IF NOT EXISTS idx_bsv_supply_package_shipment ON supply.shipment_package(shipment_id);
CREATE TABLE IF NOT EXISTS supply.movement (
  movement_id uuid PRIMARY KEY,
  request_id uuid NOT NULL,
  shipment_id uuid REFERENCES supply.shipment(shipment_id),
  package_id uuid REFERENCES supply.shipment_package(package_id),
  item_id text NOT NULL,
  lot_id text NOT NULL,
  from_location_id text NOT NULL,
  to_location_id text NOT NULL,
  qty_base numeric(18,4) NOT NULL CHECK(qty_base>0),
  actor_employee_id text NOT NULL,
  occurred_at timestamptz,
  committed_at timestamptz NOT NULL DEFAULT now(),
  CHECK(from_location_id<>to_location_id)
);
CREATE INDEX IF NOT EXISTS idx_bsv_supply_movement_from ON supply.movement(from_location_id,item_id,lot_id);
CREATE INDEX IF NOT EXISTS idx_bsv_supply_movement_to ON supply.movement(to_location_id,item_id,lot_id);
CREATE TABLE IF NOT EXISTS supply.idempotent_result (
  actor_scope text NOT NULL,
  request_id uuid NOT NULL,
  fingerprint text NOT NULL,
  response jsonb NOT NULL,
  committed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(actor_scope,request_id)
);
CREATE TABLE IF NOT EXISTS supply.stock_count (
  count_id uuid PRIMARY KEY,
  location_id text NOT NULL,
  item_id text NOT NULL,
  observer_employee_id text NOT NULL,
  full_package_count integer NOT NULL CHECK(full_package_count>=0),
  opened_count integer NOT NULL CHECK(opened_count>=0),
  opened_bucket_pct integer CHECK(opened_bucket_pct IN (0,25,50,75,100)),
  method text NOT NULL CHECK(method IN ('FIVE_BUCKET','UNKNOWN','EXACT_MEASUREMENT')),
  observed_at timestamptz NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT now(),
  -- 不存在直接触发正式库存结转的触发器；盘点只是观测。
  CHECK (NOT (method='FIVE_BUCKET' AND opened_count>1))
);
-- 公司若已有 outbox/audit，必须复用，不能按此提案再造。
-- 生产 ledger 的函数须：BEGIN -> 幂等键/包装状态/权限验证 -> SELECT FOR UPDATE 库存来源
-- -> 同事务 movement/余额投影/outbox 提交 -> 返回版本。禁止负库存、重复结算。
