BEGIN;

ALTER TABLE companies ADD COLUMN IF NOT EXISTS code VARCHAR(40) DEFAULT '';
ALTER TABLE companies ADD COLUMN IF NOT EXISTS next_order_sequence INTEGER DEFAULT 1;
UPDATE companies SET code = '' WHERE code IS NULL;
UPDATE companies SET next_order_sequence = 1 WHERE next_order_sequence IS NULL OR next_order_sequence < 1;
CREATE UNIQUE INDEX IF NOT EXISTS uq_companies_code_nonempty ON companies(code) WHERE code <> '';

CREATE TABLE IF NOT EXISTS spus (
    id SERIAL PRIMARY KEY,
    code VARCHAR(40) NOT NULL UNIQUE,
    product_name VARCHAR(160) NOT NULL,
    style_name VARCHAR(160) NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS ix_spus_code ON spus(code);
CREATE INDEX IF NOT EXISTS ix_spus_product_name ON spus(product_name);
CREATE INDEX IF NOT EXISTS ix_spus_style_name ON spus(style_name);

CREATE TABLE IF NOT EXISTS sales_orders (
    id SERIAL PRIMARY KEY,
    system_order_no VARCHAR(160) NOT NULL UNIQUE,
    customer_order_no VARCHAR(160) NOT NULL DEFAULT '',
    company_id INTEGER NOT NULL REFERENCES companies(id),
    company_sequence INTEGER NOT NULL,
    spu_id INTEGER NOT NULL REFERENCES spus(id),
    product_name VARCHAR(160) NOT NULL,
    style_name VARCHAR(160) NOT NULL,
    color_name VARCHAR(120) NOT NULL DEFAULT '',
    color_code VARCHAR(40) NOT NULL DEFAULT '',
    order_date VARCHAR(30) NOT NULL,
    delivery_date VARCHAR(80) NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_sales_orders_company_sequence UNIQUE (company_id, company_sequence)
);
CREATE INDEX IF NOT EXISTS ix_sales_orders_system_order_no ON sales_orders(system_order_no);
CREATE INDEX IF NOT EXISTS ix_sales_orders_customer_order_no ON sales_orders(customer_order_no);
CREATE INDEX IF NOT EXISTS ix_sales_orders_company_id ON sales_orders(company_id);
CREATE INDEX IF NOT EXISTS ix_sales_orders_spu_id ON sales_orders(spu_id);
CREATE INDEX IF NOT EXISTS ix_sales_orders_order_date ON sales_orders(order_date);
CREATE INDEX IF NOT EXISTS ix_sales_orders_status ON sales_orders(status);

ALTER TABLE order_lines ADD COLUMN IF NOT EXISTS order_id INTEGER REFERENCES sales_orders(id);
ALTER TABLE order_lines ADD COLUMN IF NOT EXISTS customer_sku VARCHAR(255) DEFAULT '';
CREATE INDEX IF NOT EXISTS ix_order_lines_order_id ON order_lines(order_id);

ALTER TABLE packing_drafts ADD COLUMN IF NOT EXISTS order_id INTEGER REFERENCES sales_orders(id);
CREATE INDEX IF NOT EXISTS ix_packing_drafts_order_id ON packing_drafts(order_id);

ALTER TABLE shipment_reports ADD COLUMN IF NOT EXISTS order_id INTEGER REFERENCES sales_orders(id);
CREATE INDEX IF NOT EXISTS ix_shipment_reports_order_id ON shipment_reports(order_id);

GRANT ALL PRIVILEGES ON TABLE spus, sales_orders TO zy_shipping;
GRANT ALL PRIVILEGES ON SEQUENCE spus_id_seq, sales_orders_id_seq TO zy_shipping;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE companies, order_lines, packing_drafts, shipment_reports TO zy_shipping;
ALTER TABLE spus DISABLE ROW LEVEL SECURITY;
ALTER TABLE sales_orders DISABLE ROW LEVEL SECURITY;

COMMIT;
