BEGIN;

ALTER TABLE packing_drafts ADD COLUMN IF NOT EXISTS shipping_method VARCHAR(20) DEFAULT '';
ALTER TABLE packing_drafts ADD COLUMN IF NOT EXISTS package_count INTEGER DEFAULT 0;
ALTER TABLE packing_drafts ADD COLUMN IF NOT EXISTS weight_kg DOUBLE PRECISION DEFAULT 0;

UPDATE packing_drafts SET shipping_method = '' WHERE shipping_method IS NULL;
UPDATE packing_drafts SET package_count = 0 WHERE package_count IS NULL;
UPDATE packing_drafts SET weight_kg = 0 WHERE weight_kg IS NULL;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE packing_drafts TO zy_shipping;

COMMIT;
