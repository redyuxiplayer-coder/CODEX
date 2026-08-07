-- 2026-08-07：快递渠道 + 未挂原因
-- 用 postgres 管理员执行（应用账号无 ALTER 权限）：
--   sudo -u postgres psql -d zy_shipping -f scripts/migration_2026_08_07.sql

ALTER TABLE waybill_records ADD COLUMN IF NOT EXISTS courier VARCHAR(30) NOT NULL DEFAULT '中通';
ALTER TABLE shipment_reports ADD COLUMN IF NOT EXISTS unlinked_reason VARCHAR(200) NOT NULL DEFAULT '';
