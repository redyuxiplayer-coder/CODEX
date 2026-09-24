BEGIN;

ALTER TABLE order_lines ADD COLUMN IF NOT EXISTS unit_price NUMERIC(12, 2);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_order_lines_unit_price_nonnegative'
          AND conrelid = 'order_lines'::regclass
    ) THEN
        ALTER TABLE order_lines
            ADD CONSTRAINT ck_order_lines_unit_price_nonnegative
            CHECK (unit_price IS NULL OR unit_price >= 0);
    END IF;
END $$;

COMMIT;
