# Auto-Sync Engine Specification

## Overview

This document specifies the Auto-Sync Engine design using **only existing database tables**. No new tables will be created.

---

## Existing Tables to be Used

| Table | Purpose in Auto-Sync |
|-------|---------------------|
| `SyncJob` | Work queue for all sync operations (polling, pushing) |
| `SyncLog` | Audit trail for sync operations |
| `MarketplaceOrder` | Tracks imported orders with idempotency |
| `WarehouseStock` | Master inventory (source of truth) |
| `MarketplaceListing` | Linked marketplace listings |
| `StockLedgerEntry` | Audit trail for stock changes |
| `Store` | Marketplace connections (Amazon, eBay) |
| `FeedStatus` | Amazon SP-API feed tracking |

---

## Phase 1: Order Import (Marketplace → Warehouse Stock)

### Goal
Automatically poll Amazon MFN and eBay for new orders every 5 minutes, import them, and reduce warehouse stock.

### Existing Infrastructure
- `MarketplaceOrderProcessor` already handles idempotent order processing with row-level locking
- `MarketplaceOrder` model has `idempotency_key` to prevent duplicate processing
- `StockLedgerEntry` logs all stock changes

### Implementation Plan

1. **Order Polling Job Type**
   - Add new `job_type` values to `SyncJob`: `'order_import_amazon'`, `'order_import_ebay'`
   - Scheduler enqueues these jobs every 5 minutes

2. **Amazon MFN Order Import**
   - Use SP-API Orders API to fetch orders since `last_orders_sync_at` (stored in `Store.last_sync`)
   - Filter for `MFN` (Merchant Fulfilled) orders only
   - For each order item:
     - Map `SellerSKU` → `MarketplaceListing.external_sku` → `WarehouseStock` (via `warehouse_stock_id`)
     - Call `MarketplaceOrderProcessor.process_order()` to decrement stock
     - Record creates `MarketplaceOrder` and `StockLedgerEntry`

3. **eBay Order Import**
   - Use eBay Fulfillment API (getOrders) to fetch orders since last sync
   - Map `legacyItemId` or `sku` → `MarketplaceListing` → `WarehouseStock`
   - Same processing flow as Amazon

4. **FBA Orders**
   - **Read-only**: FBA orders are fulfilled by Amazon, no warehouse stock change
   - Import for visibility only (status tracking), mark `fulfillment_type='FBA'`

5. **Logging**
   - Use existing `SyncLog` with status `'order_import'` and message containing order count
   - Use existing `SyncJob.error_message` for failures

### Data Flow
```
Marketplace API → Order Data → MarketplaceOrderProcessor
                                    ↓
                            WarehouseStock.available_quantity -= qty
                                    ↓
                            MarketplaceOrder (idempotent record)
                                    ↓
                            StockLedgerEntry (audit)
```

---

## Phase 2: Warehouse Auto-Update Event

### Goal
After warehouse stock changes (from order import or manual adjustment), automatically trigger pushes to all linked marketplaces.

### Existing Infrastructure
- `WarehousePushCoordinator` already handles preparing and enqueueing push jobs
- `warehouse_push_coordinator.py` has `prepare_for_items()` and `enqueue_pending_jobs()`

### Implementation Plan

1. **Trigger Points**
   - After `MarketplaceOrderProcessor.process_order()` succeeds
   - After manual warehouse stock adjustment (already implemented in routes.py)
   - After stock receiving/receiving_service.py

2. **UpdateLinkedListings Function**
   ```python
   def update_linked_listings(warehouse_stock_id: int):
       """Find all linked listings and enqueue push jobs"""
       from warehouse_push_coordinator import WarehousePushCoordinator
       
       ws = WarehouseStock.query.get(warehouse_stock_id)
       if not ws:
           return 0
       
       coordinator = WarehousePushCoordinator()
       prepared = coordinator.prepare_for_items([ws.sku], operation="stock_change")
       enqueued = coordinator.enqueue_pending_jobs()
       
       return enqueued
   ```

3. **Skip FBA Listings**
   - `WarehousePushCoordinator` already filters out FBA listings (`amazon_fulfillment_channel == 'AFN'`)
   - Enforced in `smart_push_service.py` via `is_pushable` property

4. **Logging**
   - `SyncJob` records each push job with `job_type='push_item'`
   - `SyncLog` records push results

---

## Phase 3: Marketplace Stock Push (Warehouse → Amazon/eBay)

### Goal
Push updated warehouse quantities to Amazon FBM and eBay listings.

### Existing Infrastructure
- `smart_push_service.py` - Handles classification and push logic
- `amazon_service.py` - Amazon SP-API inventory updates
- `ebay_service.py` - eBay ReviseInventoryStatus API
- `queue_manager.py` - Job queue management

### Implementation Plan

1. **Amazon FBM Push**
   - Already implemented in `AmazonAPIService.update_inventory_quantity()`
   - Uses SP-API Listings Feed or direct inventory API
   - Updates `MarketplaceListing.last_push_at` and `last_push_status`

2. **eBay Push**
   - Already implemented in `eBayAPIService.push_quantity()`
   - Uses `ReviseInventoryStatus` API
   - Updates `MarketplaceListing.last_push_at` and `last_push_status`

3. **FBA Safety Guard**
   - `MarketplaceListing.is_pushable` property returns `False` for FBA
   - `smart_push_service.get_pushable_listings()` filters out `AFN` listings
   - No code changes needed, just verification

4. **Push Result Tracking**
   - Use `MarketplaceListing.last_push_status` ('success', 'failed', 'pending')
   - Use `MarketplaceListing.last_push_at` for timestamp
   - Use `MarketplaceListing.last_push_error` for error messages

---

## Phase 4: Push Queue + Recovery

### Goal
Retry failed pushes automatically and auto-heal broken links.

### Existing Infrastructure
- `SyncJob` has `retry_at`, `retry_count`, `status` fields
- `sync_dispatcher.py` has watchdog for stuck jobs
- `queue_manager.py` has `mark_job_failed()` with retry logic

### Implementation Plan

1. **Retry Logic** (already exists)
   - `SyncJob.retry_count` tracks attempts
   - `SyncJob.retry_at` schedules next retry
   - Max retries defined in `Store.max_retry_attempts`

2. **Enhanced Retry Scheduler**
   - Modify `sync_dispatcher._dispatcher_loop()` to check for jobs with `retry_at <= now()`
   - Re-enqueue failed jobs for retry

3. **Auto-Heal Mode**
   - Before retry, validate `MarketplaceListing.warehouse_stock_id` is still valid
   - If warehouse deleted, mark listing as unlinked
   - If SKU mismatch, attempt re-link by matching `external_sku`

4. **Failure Tracking**
   - Use `SyncJob.error_message` for detailed error
   - Use `Store.current_failure_count` for failure tracking
   - `Store.auto_disable_on_failures` for automatic circuit breaker

---

## Phase 5: Diagnostics UI

### Goal
Show per-SKU sync status, push history, and connection health.

### Existing Infrastructure
- `/api/diagnostics/sku/<sku>` endpoint exists (in routes.py)
- `SyncLog`, `SyncJob`, `MarketplaceListing` have all needed data

### Implementation Plan

1. **Enhanced SKU Diagnostics Endpoint**
   - Return warehouse quantity
   - Return all linked marketplace listings with quantities
   - Return last sync/push timestamps
   - Return last push result and errors
   - Return marketplace identifiers (ASIN, eBay Item ID)

2. **Connection Status Badges**
   - Green: Last push < 1 hour, no errors
   - Yellow: Last push > 1 hour but < 24 hours, or recent recoverable error
   - Red: Last push > 24 hours, or persistent errors

3. **Diagnostics Page**
   - Add `/diagnostics` page with search by SKU
   - Display all linked listings in a table
   - Show sync/push history

---

## Phase 6: Testing Checklist

### Pre-Implementation Tests
- [ ] Verify `MarketplaceOrderProcessor` works with test order
- [ ] Verify `WarehousePushCoordinator` enqueues jobs correctly
- [ ] Verify `smart_push_service` skips FBA listings

### Phase 1 Tests
- [ ] Amazon order import creates `MarketplaceOrder` record
- [ ] Warehouse stock decremented after order import
- [ ] Duplicate order rejected (idempotency)
- [ ] eBay order import works similarly

### Phase 2 Tests
- [ ] Stock change triggers push job enqueueing
- [ ] Push job appears in `SyncJob` queue
- [ ] FBA listings NOT queued for push

### Phase 3 Tests
- [ ] Amazon FBM push succeeds
- [ ] eBay push succeeds
- [ ] `last_push_at` and `last_push_status` updated

### Phase 4 Tests
- [ ] Failed push retried after delay
- [ ] Max retries respected
- [ ] Circuit breaker triggers on repeated failures

### Phase 5 Tests
- [ ] Diagnostics show correct warehouse qty
- [ ] Diagnostics show all linked listings
- [ ] Status badges display correctly

---

## Implementation Order

1. **Phase 1**: Order Import (most impactful for stock accuracy)
2. **Phase 2**: Auto-Update Event (wires order import to push)
3. **Phase 3**: Verify/enhance marketplace push (may already work)
4. **Phase 4**: Retry logic (resilience)
5. **Phase 5**: Diagnostics UI (visibility)
6. **Phase 6**: End-to-end testing

---

## Files to Modify

| File | Changes |
|------|---------|
| `sync_dispatcher.py` | Add order import job scheduling |
| `amazon_service.py` | Add `get_orders()` method for MFN orders |
| `ebay_service.py` | Add `get_orders()` method |
| `marketplace_order_processor.py` | Integrate with push coordinator |
| `routes.py` | Add diagnostics page route |
| `templates/diagnostics.html` | New diagnostics UI |

---

## No Schema Changes Required

All functionality uses existing columns:
- `SyncJob.job_type` accepts new values ('order_import_amazon', 'order_import_ebay')
- `MarketplaceOrder` already tracks all order data
- `SyncLog` handles all audit logging
- `MarketplaceListing` has push tracking fields
