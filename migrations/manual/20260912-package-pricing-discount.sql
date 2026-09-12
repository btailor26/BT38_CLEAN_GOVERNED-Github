ALTER TABLE subscription_packages
    ADD COLUMN IF NOT EXISTS list_price_pence INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS discount_percent NUMERIC(5,2) NOT NULL DEFAULT 0;

UPDATE subscription_packages
SET list_price_pence = price_pence
WHERE list_price_pence = 0 AND price_pence > 0;

ALTER TABLE subscription_packages
    DROP CONSTRAINT IF EXISTS ck_subscription_packages_list_price_nonnegative,
    ADD CONSTRAINT ck_subscription_packages_list_price_nonnegative CHECK (list_price_pence >= 0),
    DROP CONSTRAINT IF EXISTS ck_subscription_packages_discount_percent,
    ADD CONSTRAINT ck_subscription_packages_discount_percent CHECK (discount_percent >= 0 AND discount_percent <= 100),
    DROP CONSTRAINT IF EXISTS ck_subscription_packages_customer_not_above_marked,
    ADD CONSTRAINT ck_subscription_packages_customer_not_above_marked CHECK (list_price_pence = 0 OR price_pence <= list_price_pence);
