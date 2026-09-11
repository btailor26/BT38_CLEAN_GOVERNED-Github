CREATE TABLE IF NOT EXISTS revolut_subscription_bindings (
    id SERIAL PRIMARY KEY,
    assignment_id INTEGER NOT NULL REFERENCES account_package_assignments(id) ON DELETE CASCADE,
    customer_ref VARCHAR(180) NULL,
    subscription_ref VARCHAR(180) NULL,
    setup_order_ref VARCHAR(180) NULL,
    provider_state VARCHAR(40) NULL,
    last_event VARCHAR(80) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_revolut_binding_assignment UNIQUE (assignment_id),
    CONSTRAINT uq_revolut_binding_subscription UNIQUE (subscription_ref)
);

CREATE INDEX IF NOT EXISTS ix_revolut_subscription_bindings_assignment_id
    ON revolut_subscription_bindings (assignment_id);
CREATE INDEX IF NOT EXISTS ix_revolut_subscription_bindings_customer_ref
    ON revolut_subscription_bindings (customer_ref);
CREATE INDEX IF NOT EXISTS ix_revolut_subscription_bindings_subscription_ref
    ON revolut_subscription_bindings (subscription_ref);
CREATE INDEX IF NOT EXISTS ix_revolut_subscription_bindings_setup_order_ref
    ON revolut_subscription_bindings (setup_order_ref);
