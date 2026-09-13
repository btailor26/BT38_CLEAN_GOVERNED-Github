CREATE TABLE IF NOT EXISTS support_case_attachments (
    id SERIAL PRIMARY KEY,
    case_pk INTEGER NOT NULL REFERENCES support_cases(id) ON DELETE CASCADE,
    uploaded_by_user_id INTEGER NOT NULL,
    uploader_role VARCHAR(20) NOT NULL DEFAULT 'customer',
    filename VARCHAR(220) NOT NULL,
    content_type VARCHAR(80) NOT NULL,
    byte_size INTEGER NOT NULL,
    sha256_hex VARCHAR(64) NOT NULL,
    payload BYTEA NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_support_case_attachments_case_pk
    ON support_case_attachments(case_pk);
CREATE INDEX IF NOT EXISTS ix_support_case_attachments_uploaded_by_user_id
    ON support_case_attachments(uploaded_by_user_id);
CREATE INDEX IF NOT EXISTS ix_support_case_attachments_sha256_hex
    ON support_case_attachments(sha256_hex);
CREATE INDEX IF NOT EXISTS ix_support_case_attachments_created_at
    ON support_case_attachments(created_at);
