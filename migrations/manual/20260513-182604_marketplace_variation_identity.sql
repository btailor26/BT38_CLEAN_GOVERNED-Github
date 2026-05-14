-- BT38 variation-safe marketplace identity migration
-- Purpose:
-- Replace old ItemID-only uniqueness with ItemID + external_sku uniqueness
-- Required for eBay variation stability

BEGIN;

-- Remove old unique index if it exists
DROP INDEX IF EXISTS idx_store_external_listing;

-- Create new variation-safe unique index
CREATE UNIQUE INDEX IF NOT EXISTS idx_store_external_listing_sku
ON marketplace_listings (
    store_id,
    external_listing_id,
    external_sku
);

COMMIT;
