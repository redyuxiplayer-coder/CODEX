BEGIN;

CREATE TABLE IF NOT EXISTS sales_order_archives (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES sales_orders(id),
    archived_by INTEGER NOT NULL REFERENCES users(id),
    archived_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    restored_by INTEGER REFERENCES users(id),
    restored_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_sales_order_archives_order_id
    ON sales_order_archives(order_id);
CREATE INDEX IF NOT EXISTS ix_sales_order_archives_archived_by
    ON sales_order_archives(archived_by);
CREATE INDEX IF NOT EXISTS ix_sales_order_archives_archived_at
    ON sales_order_archives(archived_at);
CREATE INDEX IF NOT EXISTS ix_sales_order_archives_restored_at
    ON sales_order_archives(restored_at);

GRANT ALL PRIVILEGES ON TABLE sales_order_archives TO zy_shipping;
GRANT USAGE, SELECT ON SEQUENCE sales_order_archives_id_seq TO zy_shipping;
ALTER TABLE sales_order_archives DISABLE ROW LEVEL SECURITY;

COMMIT;
