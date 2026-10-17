BEGIN;

ALTER TABLE order_lines
    ALTER COLUMN unit_price TYPE NUMERIC(13, 3)
    USING unit_price::NUMERIC(13, 3);

COMMIT;
