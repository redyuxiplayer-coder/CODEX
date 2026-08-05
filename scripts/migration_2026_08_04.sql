-- 2026-08-04 发货系统九项改进 + 管理端新界面 数据库迁移
-- 用法：sudo -u postgres psql -d zy_shipping -f /home/ubuntu/zy-shipping/scripts/migration_2026_08_04.sql
-- 加列（必执行；若已存在会自动跳过）
ALTER TABLE order_lines ADD COLUMN IF NOT EXISTS sku VARCHAR(255) DEFAULT '';
ALTER TABLE sku_mappings ADD COLUMN IF NOT EXISTS barcode VARCHAR(255) DEFAULT '';
ALTER TABLE packing_drafts ADD COLUMN IF NOT EXISTS package_no VARCHAR(40) DEFAULT '';
ALTER TABLE packing_drafts ADD COLUMN IF NOT EXISTS waybill_no VARCHAR(80) DEFAULT '';
ALTER TABLE shipment_reports ADD COLUMN IF NOT EXISTS waybill_no VARCHAR(80) DEFAULT '';
-- 新表（服务启动会自动创建；若数据库账号无建表权限，则手动执行下面部分）

CREATE TABLE IF NOT EXISTS order_ledger_entries (
	id SERIAL NOT NULL, 
	order_line_id INTEGER NOT NULL, 
	movement_type VARCHAR(30) NOT NULL, 
	quantity INTEGER NOT NULL, 
	reason TEXT NOT NULL, 
	ref_report_id INTEGER, 
	ref_return_id INTEGER, 
	ref_adjustment_id INTEGER, 
	ref_close_id INTEGER, 
	created_by INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(order_line_id) REFERENCES order_lines (id), 
	FOREIGN KEY(ref_report_id) REFERENCES shipment_reports (id), 
	FOREIGN KEY(ref_return_id) REFERENCES return_reworks (id), 
	FOREIGN KEY(ref_adjustment_id) REFERENCES order_adjustments (id), 
	FOREIGN KEY(ref_close_id) REFERENCES order_line_closes (id), 
	FOREIGN KEY(created_by) REFERENCES users (id)
)

;

CREATE TABLE IF NOT EXISTS return_reworks (
	id SERIAL NOT NULL, 
	order_line_id INTEGER NOT NULL, 
	report_id INTEGER, 
	quantity INTEGER NOT NULL, 
	reason_type VARCHAR(80) NOT NULL, 
	reason TEXT NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	created_by INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(order_line_id) REFERENCES order_lines (id), 
	FOREIGN KEY(report_id) REFERENCES shipment_reports (id), 
	FOREIGN KEY(created_by) REFERENCES users (id)
)

;

CREATE TABLE IF NOT EXISTS return_rework_photos (
	id SERIAL NOT NULL, 
	return_id INTEGER NOT NULL, 
	file_path VARCHAR(500) NOT NULL, 
	original_name VARCHAR(255) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(return_id) REFERENCES return_reworks (id)
)

;

CREATE TABLE IF NOT EXISTS order_adjustments (
	id SERIAL NOT NULL, 
	order_line_id INTEGER NOT NULL, 
	quantity INTEGER NOT NULL, 
	reason TEXT NOT NULL, 
	created_by INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(order_line_id) REFERENCES order_lines (id), 
	FOREIGN KEY(created_by) REFERENCES users (id)
)

;

CREATE TABLE IF NOT EXISTS order_line_closes (
	id SERIAL NOT NULL, 
	order_line_id INTEGER NOT NULL, 
	quantity INTEGER NOT NULL, 
	reason TEXT NOT NULL, 
	created_by INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(order_line_id) REFERENCES order_lines (id), 
	FOREIGN KEY(created_by) REFERENCES users (id)
)

;

CREATE TABLE IF NOT EXISTS order_line_comments (
	id SERIAL NOT NULL, 
	order_line_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	content TEXT NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(order_line_id) REFERENCES order_lines (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)

;

-- 快递记录（2026-08-05 新增）
ALTER TABLE shipment_reports ADD COLUMN IF NOT EXISTS waybill_id INTEGER;

CREATE TABLE IF NOT EXISTS waybill_records (
	id SERIAL NOT NULL, 
	company_name VARCHAR(120) NOT NULL, 
	ship_date VARCHAR(30) NOT NULL, 
	waybill_no VARCHAR(80) NOT NULL, 
	weight_kg FLOAT NOT NULL, 
	package_count INTEGER NOT NULL, 
	note TEXT NOT NULL, 
	created_by INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(created_by) REFERENCES users (id)
)

;
CREATE UNIQUE INDEX IF NOT EXISTS ix_waybill_records_waybill_no ON waybill_records (waybill_no);
