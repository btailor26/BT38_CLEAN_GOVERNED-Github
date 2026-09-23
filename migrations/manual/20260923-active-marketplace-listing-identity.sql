-- BT38 marketplace listing identity alignment
--
-- BT38 listing IDs are permanent audit/history identities.
-- Marketplace identity is unique only while a listing is active.
-- Retired/inactive rows keep their original marketplace identifiers and must
-- not reserve those identifiers against a current active listing.
--
-- Production was audited before this migration: no duplicate active
-- (store_id, external_listing_id, external_sku) tuples exist.

BEGIN;

DROP INDEX IF EXISTS idx_store_external_listing_sku;

CREATE UNIQUE INDEX idx_store_external_listing_sku
    ON marketplace_listings (store_id, external_listing_id, external_sku)
    WHERE is_active = TRUE;

COMMIT;
