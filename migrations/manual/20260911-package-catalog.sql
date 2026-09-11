CREATE TABLE IF NOT EXISTS subscription_packages (
    id SERIAL PRIMARY KEY,
    code VARCHAR(48) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    description VARCHAR(500) NULL,
    tier_type VARCHAR(12) NOT NULL DEFAULT 'free',
    price_pence INTEGER NOT NULL DEFAULT 0,
    currency VARCHAR(3) NOT NULL DEFAULT 'GBP',
    billing_interval VARCHAR(12) NOT NULL DEFAULT 'none',
    user_limit INTEGER NOT NULL DEFAULT 1,
    marketplace_limit INTEGER NULL,
    monthly_order_limit INTEGER NULL,
    features JSON NOT NULL DEFAULT '[]',
    revolut_plan_ref VARCHAR(180) NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_subscription_packages_tier_type CHECK (tier_type IN ('free', 'paid')),
    CONSTRAINT ck_subscription_packages_price_nonnegative CHECK (price_pence >= 0),
    CONSTRAINT ck_subscription_packages_billing_interval CHECK (billing_interval IN ('none', 'month', 'year')),
    CONSTRAINT ck_subscription_packages_user_limit_positive CHECK (user_limit > 0),
    CONSTRAINT ck_subscription_packages_marketplace_limit_positive CHECK (marketplace_limit IS NULL OR marketplace_limit > 0),
    CONSTRAINT ck_subscription_packages_monthly_order_limit_positive CHECK (monthly_order_limit IS NULL OR monthly_order_limit > 0),
    CONSTRAINT ck_subscription_packages_free_shape CHECK (
        tier_type <> 'free'
        OR (price_pence = 0 AND billing_interval = 'none' AND revolut_plan_ref IS NULL)
    ),
    CONSTRAINT ck_subscription_packages_paid_shape CHECK (
        tier_type <> 'paid'
        OR (price_pence > 0 AND billing_interval IN ('month', 'year'))
    )
);

CREATE INDEX IF NOT EXISTS ix_subscription_packages_code
    ON subscription_packages (code);

CREATE TABLE IF NOT EXISTS account_package_assignments (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES customer_accounts(id) ON DELETE CASCADE,
    package_id INTEGER NOT NULL REFERENCES subscription_packages(id) ON DELETE RESTRICT,
    status VARCHAR(24) NOT NULL DEFAULT 'active',
    billing_provider VARCHAR(24) NOT NULL DEFAULT 'none',
    provider_subscription_ref VARCHAR(180) NULL,
    assigned_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    starts_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ends_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_account_package_assignment_account UNIQUE (account_id),
    CONSTRAINT ck_account_package_assignment_status CHECK (
        status IN ('setup_pending', 'trial', 'active', 'past_due', 'cancelled')
    ),
    CONSTRAINT ck_account_package_assignment_provider CHECK (
        billing_provider IN ('none', 'manual', 'revolut')
    )
);

CREATE INDEX IF NOT EXISTS ix_account_package_assignments_account_id
    ON account_package_assignments (account_id);
CREATE INDEX IF NOT EXISTS ix_account_package_assignments_package_id
    ON account_package_assignments (package_id);
