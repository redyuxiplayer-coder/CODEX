BEGIN;

ALTER TABLE order_lines ADD COLUMN IF NOT EXISTS unit_price NUMERIC(13, 3);
ALTER TABLE order_lines ADD COLUMN IF NOT EXISTS price_revision INTEGER NOT NULL DEFAULT 0;
UPDATE order_lines SET price_revision = 0 WHERE price_revision IS NULL;
ALTER TABLE order_lines ALTER COLUMN price_revision SET DEFAULT 0;
ALTER TABLE order_lines ALTER COLUMN price_revision SET NOT NULL;

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

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_order_lines_price_revision_nonnegative'
          AND conrelid = 'order_lines'::regclass
    ) THEN
        ALTER TABLE order_lines
            ADD CONSTRAINT ck_order_lines_price_revision_nonnegative
            CHECK (price_revision >= 0);
    END IF;
END $$;

COMMIT;
