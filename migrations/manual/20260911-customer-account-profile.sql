CREATE TABLE IF NOT EXISTS customer_accounts (
    id SERIAL PRIMARY KEY,
    owner_user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE RESTRICT,
    business_name VARCHAR(180) NULL,
    logo_data BYTEA NULL,
    logo_mime VARCHAR(40) NULL,
    plan_name VARCHAR(80) NOT NULL DEFAULT 'BT38',
    billing_status VARCHAR(30) NOT NULL DEFAULT 'setup_pending',
    user_limit INTEGER NOT NULL DEFAULT 5,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_customer_accounts_owner_user_id
    ON customer_accounts (owner_user_id);

CREATE TABLE IF NOT EXISTS customer_account_members (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES customer_accounts(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    access_preset VARCHAR(40) NOT NULL DEFAULT 'assistant',
    is_owner BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_customer_account_member UNIQUE (account_id, user_id),
    CONSTRAINT uq_customer_account_member_user UNIQUE (user_id)
);

CREATE INDEX IF NOT EXISTS ix_customer_account_members_account_id
    ON customer_account_members (account_id);
CREATE INDEX IF NOT EXISTS ix_customer_account_members_user_id
    ON customer_account_members (user_id);

CREATE TABLE IF NOT EXISTS user_profiles (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    display_name VARCHAR(140) NULL,
    position VARCHAR(140) NULL,
    setup_required BOOLEAN NOT NULL DEFAULT FALSE,
    setup_completed_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
