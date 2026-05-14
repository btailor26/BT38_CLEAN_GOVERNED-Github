# BT38 Settings Control Center Inventory Map

## Locked Truth Rules — Display Only
- Warehouse is source of truth
- Marketplace overwrite warehouse disabled
- FBA read-only
- FBM warehouse-authoritative
- Group cascade controlled by warehouse truth
- Reverse sync disabled by default
- Queue/lock protection must not be weakened

## Existing Global Settings
- global_push_enabled
- default_push_frequency_minutes
- default_batch_size
- default_retry_attempts
- enable_batch_scheduling
- batch_schedule_minutes
- off_hours_only
- off_hours_start
- off_hours_end
- require_confirmation_threshold
- auto_pause_on_errors
- error_rate_threshold
- notify_on_large_pushes
- notify_on_failures
- daily_summary_enabled
- concurrent_store_pushes
- api_rate_limit_buffer

## Existing Store Settings
- is_active
- auto_push_enabled
- push_priority
- push_frequency_minutes
- push_batch_size
- push_on_quantity_change
- push_on_price_change
- push_on_item_create
- push_on_item_update
- max_retry_attempts
- auto_disable_on_failures
- failure_threshold
- immediate_push
- large_change_confirmation
- large_change_threshold
- fbm_sync_enabled
- fba_import_enabled
- reverse_sync_enabled
- sync_priority_policy
- sync_status
- last_sync

## Existing Runtime / API Controls
- /settings GET
- /settings POST
- /api/push-settings GET
- /api/reset-push-settings POST
- /api/store-push-settings/<store_id> POST
- /api/auto-sync/toggle
- /api/auto-sync/dry-run-logs
- /api/sync_store/<store_id>
- /api/diagnostics/amazon/health

## New Page Sections

### 1. System Status
Displays runtime cards only.

### 2. Master Runtime Control
Contains global settings.

### 3. Marketplace Control
Contains Amazon FBA, Amazon FBM, eBay, TikTok, Shopify controls.

### 4. Store Control
Contains per-store toggles and trigger settings.

### 5. Workers & Queues
Shows worker/queue controls and status.

### 6. Safety & Governance
Shows locked truth rules and editable safety thresholds.

### 7. Logs
Shows system logs, sync logs, failures, dry-run logs.

## Rule
Every backend setting must appear on this page either as:
- editable control
- read-only status
- locked truth rule
