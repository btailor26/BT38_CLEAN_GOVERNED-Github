CREATE TABLE IF NOT EXISTS billing_invoices (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES customer_accounts(id) ON DELETE RESTRICT,
    assignment_id INTEGER NOT NULL REFERENCES account_package_assignments(id) ON DELETE RESTRICT,
    package_id INTEGER NOT NULL REFERENCES subscription_packages(id) ON DELETE RESTRICT,
    provider VARCHAR(30) NOT NULL DEFAULT 'revolut',
    provider_order_ref VARCHAR(180) NOT NULL,
    provider_subscription_ref VARCHAR(180),
    invoice_number VARCHAR(40) NOT NULL UNIQUE,
    business_name VARCHAR(180) NOT NULL,
    package_name VARCHAR(100) NOT NULL,
    amount_minor BIGINT NOT NULL,
    currency VARCHAR(3) NOT NULL,
    payment_state VARCHAR(30) NOT NULL DEFAULT 'completed',
    paid_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_billing_invoice_provider_order UNIQUE (provider, provider_order_ref)
);
CREATE INDEX IF NOT EXISTS ix_billing_invoices_account_id ON billing_invoices(account_id);
CREATE INDEX IF NOT EXISTS ix_billing_invoices_assignment_id ON billing_invoices(assignment_id);
CREATE INDEX IF NOT EXISTS ix_billing_invoices_provider_order_ref ON billing_invoices(provider_order_ref);
CREATE INDEX IF NOT EXISTS ix_billing_invoices_paid_at ON billing_invoices(paid_at);
