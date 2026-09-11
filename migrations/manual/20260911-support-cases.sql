CREATE TABLE IF NOT EXISTS support_cases (
    id SERIAL PRIMARY KEY,
    case_id VARCHAR(40) UNIQUE,
    account_id INTEGER NOT NULL REFERENCES customer_accounts(id) ON DELETE CASCADE,
    opened_by_user_id INTEGER NOT NULL,
    category VARCHAR(50) NOT NULL,
    subject VARCHAR(180) NOT NULL,
    description TEXT NOT NULL,
    priority VARCHAR(20) NOT NULL DEFAULT 'normal',
    status VARCHAR(30) NOT NULL DEFAULT 'open',
    affected_area VARCHAR(160),
    source_page VARCHAR(500),
    context_json TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Safe for a database where the first support-case draft was already created.
ALTER TABLE support_cases ADD COLUMN IF NOT EXISTS context_json TEXT;
ALTER TABLE support_cases ALTER COLUMN source_page TYPE VARCHAR(500);

CREATE TABLE IF NOT EXISTS support_case_messages (
    id SERIAL PRIMARY KEY,
    case_pk INTEGER NOT NULL REFERENCES support_cases(id) ON DELETE CASCADE,
    author_user_id INTEGER,
    author_role VARCHAR(20) NOT NULL DEFAULT 'customer',
    body TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_support_cases_case_id ON support_cases(case_id);
CREATE INDEX IF NOT EXISTS ix_support_cases_account_id ON support_cases(account_id);
CREATE INDEX IF NOT EXISTS ix_support_cases_opened_by_user_id ON support_cases(opened_by_user_id);
CREATE INDEX IF NOT EXISTS ix_support_cases_category ON support_cases(category);
CREATE INDEX IF NOT EXISTS ix_support_cases_priority ON support_cases(priority);
CREATE INDEX IF NOT EXISTS ix_support_cases_status ON support_cases(status);
CREATE INDEX IF NOT EXISTS ix_support_cases_created_at ON support_cases(created_at);
CREATE INDEX IF NOT EXISTS ix_support_cases_updated_at ON support_cases(updated_at);
CREATE INDEX IF NOT EXISTS ix_support_case_messages_case_pk ON support_case_messages(case_pk);
CREATE INDEX IF NOT EXISTS ix_support_case_messages_author_user_id ON support_case_messages(author_user_id);
CREATE INDEX IF NOT EXISTS ix_support_case_messages_created_at ON support_case_messages(created_at);
