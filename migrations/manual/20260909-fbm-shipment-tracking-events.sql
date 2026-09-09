CREATE TABLE IF NOT EXISTS fbm_shipment_tracking_events (
    id SERIAL PRIMARY KEY,
    shipment_id INTEGER NOT NULL REFERENCES fbm_shipments(id) ON DELETE CASCADE,
    provider VARCHAR(50) NOT NULL DEFAULT 'packlink',
    event_key VARCHAR(180) NOT NULL,
    event_time TIMESTAMP NULL,
    status VARCHAR(120) NULL,
    description TEXT NULL,
    detail TEXT NULL,
    estimated_delivery_at TIMESTAMP NULL,
    package_count INTEGER NULL,
    package_data JSON NULL,
    raw_event JSON NOT NULL DEFAULT '{}'::json,
    observed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_fbm_tracking_event_shipment_key UNIQUE (shipment_id, event_key)
);

CREATE INDEX IF NOT EXISTS ix_fbm_shipment_tracking_events_shipment_id
    ON fbm_shipment_tracking_events (shipment_id);
CREATE INDEX IF NOT EXISTS ix_fbm_shipment_tracking_events_provider
    ON fbm_shipment_tracking_events (provider);
CREATE INDEX IF NOT EXISTS ix_fbm_shipment_tracking_events_event_time
    ON fbm_shipment_tracking_events (event_time);
CREATE INDEX IF NOT EXISTS ix_fbm_shipment_tracking_events_observed_at
    ON fbm_shipment_tracking_events (observed_at);
CREATE INDEX IF NOT EXISTS idx_fbm_tracking_event_shipment_time
    ON fbm_shipment_tracking_events (shipment_id, event_time);
