# Admin Reporting System Design

**Created:** December 2025  
**Purpose:** Comprehensive internal reporting system for tracking all system activity, configuration changes, sync jobs, and API errors.

## Overview

The Admin Reporting System provides a centralized dashboard for administrators to monitor all system activity. It captures every meaningful change, job, error, and agent action, providing full audit trail capabilities.

## Database Schema

### 1. ConfigChangeLog

Tracks all configuration changes with before/after snapshots.

```sql
CREATE TABLE config_change_log (
    id SERIAL PRIMARY KEY,
    changed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    actor_type VARCHAR(20) NOT NULL,  -- 'user', 'agent', 'system'
    actor_id INTEGER,                  -- User ID if actor_type='user'
    entity_type VARCHAR(50) NOT NULL,  -- 'store', 'push_settings', 'warehouse', etc.
    entity_id INTEGER,
    summary VARCHAR(500) NOT NULL,
    before_json JSONB,
    after_json JSONB
);

CREATE INDEX idx_config_change_entity ON config_change_log(entity_type, entity_id);
CREATE INDEX idx_config_change_at ON config_change_log(changed_at);
```

### 2. AgentRunLog

Tracks agent execution runs and their outcomes.

```sql
CREATE TABLE agent_run_log (
    id SERIAL PRIMARY KEY,
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMP,
    agent_name VARCHAR(100) NOT NULL,  -- 'replit_agent', 'sync_scheduler', etc.
    scope VARCHAR(200),
    status VARCHAR(20) DEFAULT 'running',  -- 'running', 'success', 'partial', 'failed'
    summary TEXT,
    details_json JSONB
);

CREATE INDEX idx_agent_run_started ON agent_run_log(started_at);
CREATE INDEX idx_agent_run_name ON agent_run_log(agent_name);
```

### 3. APIErrorLog

Tracks API errors from external services (Amazon, eBay).

```sql
CREATE TABLE api_error_log (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL,
    provider VARCHAR(50) NOT NULL,  -- 'amazon', 'ebay'
    endpoint VARCHAR(200),
    http_status INTEGER,
    error_code VARCHAR(100),
    message TEXT,
    raw_payload TEXT  -- Masked/truncated
);

CREATE INDEX idx_api_error_created ON api_error_log(created_at);
CREATE INDEX idx_api_error_provider ON api_error_log(provider);
CREATE INDEX idx_api_error_code ON api_error_log(error_code);
CREATE INDEX idx_api_error_store ON api_error_log(store_id, created_at);
```

### 4. SyncJobLog

Enhanced sync job logging with detailed tracking.

```sql
CREATE TABLE sync_job_log (
    id SERIAL PRIMARY KEY,
    store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL,
    job_type VARCHAR(50) NOT NULL,  -- 'fba_import', 'fbm_push', 'ebay_sync', 'auto_push'
    status VARCHAR(20) DEFAULT 'started',  -- 'started', 'completed', 'failed', 'partial'
    items_imported INTEGER DEFAULT 0,
    items_pushed INTEGER DEFAULT 0,
    items_failed INTEGER DEFAULT 0,
    message TEXT,
    error_details JSONB,
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMP,
    duration_seconds FLOAT
);

CREATE INDEX idx_sync_job_started ON sync_job_log(started_at);
CREATE INDEX idx_sync_job_type ON sync_job_log(job_type);
CREATE INDEX idx_sync_job_status ON sync_job_log(status);
CREATE INDEX idx_sync_job_store ON sync_job_log(store_id, started_at);
```

## Existing Tables (Referenced)

These tables already exist and are used for historical backfill:

- **sync_logs**: Basic sync logging (store_id, status, message, items_synced)
- **system_logs**: Generic system logs (log_type, message, details)
- **feed_status**: Amazon feed submission tracking

## Logging API

### Python Helpers (admin_logging.py)

```python
from admin_logging import log_config_change, log_api_error, SyncJobLogger

# Log a configuration change
log_config_change(
    entity_type='store',
    entity_id=80,
    summary='Updated FBM sync settings',
    before_state={'fbm_sync_enabled': False},
    after_state={'fbm_sync_enabled': True}
)

# Log an API error
log_api_error(
    provider='amazon',
    endpoint='/feeds/2021-06-30/documents',
    http_status=401,
    error_code='unauthorized_client',
    message='Token refresh failed',
    store_id=80
)

# Context manager for sync jobs
with SyncJobLogger(store_id=1, job_type='ebay_sync') as job:
    # Do sync work
    job.update(imported=50, pushed=45, failed=5)
```

## Admin UI

### Access

- **URL:** `/admin/system-activity`
- **Requires:** Admin role authentication
- **Menu:** Visible in navbar for admin users only

### Dashboard Statistics

- Sync Jobs (24h)
- Failed Jobs (24h)
- API Errors (24h)
- Config Changes (7d)

### Tabs

1. **Sync Jobs**
   - Filterable by store, status, job type
   - Shows time, store, type, imported/pushed/failed counts, status, duration
   
2. **API Errors**
   - Filterable by provider, error code
   - Shows time, store, provider, endpoint, error code, HTTP status, message
   - Click row to view full payload (masked)

3. **Config Changes**
   - Filterable by entity type, actor type
   - Shows time, actor, entity, summary
   - Click to view before/after JSON diff

4. **Agent Runs**
   - Filterable by status, agent name
   - Shows time, agent, scope, status, summary
   - Click to view full details

### Export Formats

All tabs support export in:
- **CSV**: Spreadsheet-compatible
- **JSON**: Programmatic access
- **TXT**: Human-readable

Exports respect current filters and mask sensitive data.

## Security

1. **Admin-only access**: All routes require admin role
2. **Sensitive data masking**: Tokens, secrets, keys are masked in logs
3. **Payload truncation**: Large payloads limited to 2000 characters
4. **No credential exposure**: Never logs actual API keys or passwords

## How to Query Logs

### Direct Database Queries

```sql
-- Recent API errors for Amazon
SELECT * FROM api_error_log 
WHERE provider = 'amazon' 
  AND created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC;

-- Failed sync jobs this week
SELECT * FROM sync_job_log 
WHERE status = 'failed' 
  AND started_at > NOW() - INTERVAL '7 days'
ORDER BY started_at DESC;

-- Config changes by users
SELECT * FROM config_change_log 
WHERE actor_type = 'user'
ORDER BY changed_at DESC
LIMIT 100;
```

### API Endpoints

```bash
# Get sync jobs (paginated)
GET /admin/api/sync-jobs?page=1&store_id=80&status=failed

# Get API errors
GET /admin/api/api-errors?provider=amazon&page=1

# Get config changes
GET /admin/api/config-changes?entity_type=store

# Export logs
GET /admin/api/export/sync_jobs?format=csv
GET /admin/api/export/api_errors?format=json
```

## Investigation Examples

### "When did Amazon auth start failing?"

```sql
SELECT created_at, error_code, message 
FROM api_error_log 
WHERE provider = 'amazon' 
  AND error_code ILIKE '%unauthorized%'
ORDER BY created_at ASC
LIMIT 10;
```

### "Who changed store settings last week?"

```sql
SELECT changed_at, actor_type, actor_id, summary 
FROM config_change_log 
WHERE entity_type = 'store'
  AND changed_at > NOW() - INTERVAL '7 days'
ORDER BY changed_at DESC;
```

### "How many items were pushed today?"

```sql
SELECT SUM(items_pushed) as total_pushed, 
       SUM(items_failed) as total_failed
FROM sync_job_log 
WHERE started_at > CURRENT_DATE
  AND status IN ('completed', 'partial');
```

### "Find all rate limit errors"

```sql
SELECT created_at, store_id, endpoint, message 
FROM api_error_log 
WHERE http_status = 429 
   OR error_code ILIKE '%rate%' 
   OR error_code ILIKE '%throttl%'
ORDER BY created_at DESC;
```

## Backfill Process

Historical data can be backfilled from existing tables:

```python
from admin_logging import backfill_from_sync_logs, backfill_from_system_logs

# Backfill SyncJobLog from sync_logs
backfill_from_sync_logs()

# Backfill APIErrorLog from system_logs
backfill_from_system_logs()
```

Or via API:

```bash
POST /admin/api/backfill
```

## Files

- **models.py**: Database models (ConfigChangeLog, AgentRunLog, APIErrorLog, SyncJobLog)
- **admin_logging.py**: Logging helper functions
- **admin_routes.py**: Admin blueprint with API endpoints
- **templates/admin/system_activity.html**: Admin dashboard UI
