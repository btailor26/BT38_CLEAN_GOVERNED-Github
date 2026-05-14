# Phase 1: FBA/FBM Current State Analysis

## 1. Tables/Fields Indicating FBA vs FBM

### Store Model (models.py line 223)
- `platform` field distinguishes store types: `'AmazonFBA'`, `'AmazonFBM'`, `'eBay'`, etc.
- Each Amazon store is either FBA or FBM based on this field

### Separate Listing Models
- `AmazonFBAListing` (line 1641) - FBA-specific with read-only inventory fields
  - Has `warehouse_stock_id` linking to WarehouseStock
  - Fields: `sellable_quantity`, `reserved_quantity`, `inbound_quantity` (Amazon-controlled)
  - `fulfillment_channel` property always returns `'FBA'`
  
- `AmazonFBMListing` (line 1757) - FBM with warehouse control
  - Has `warehouse_stock_id` linking to WarehouseStock
  - Fields for shipping settings, etc.
  - `fulfillment_channel` property always returns `'FBM'`

### MarketplaceListing Model (line 1492)
- Generic listing linked via `store_id` to Store
- FBA/FBM determined by `store.platform`
- Field `amazon_fulfillment_channel` exists (line 1508) but appears underutilized

## 2. Routes/Endpoints That Can Push Stock for Amazon

| Endpoint | Location | FBA Block? |
|----------|----------|------------|
| `/push_stock/<item_id>` | routes.py:6064 | YES (line 6091) |
| `/push_stock_bulk` | routes.py:6154 | YES (line 6211) |
| `/push_stock_all` | routes.py:6482 | YES (lines 6523) |
| `SmartPushService.push_to_store()` | smart_push_service.py:214 | YES (line 229) |
| `SmartPushService.get_pushable_listings()` | smart_push_service.py:81 | YES (lines 92, 98) |
| `SyncDispatcher._execute_job()` | sync_dispatcher.py:224 | YES (lines 230-232) |

**GOOD NEWS**: Backend has FBA blocking in place at multiple levels.

## 3. Critical Problem: Warehouse Stock Page Shows FBA SKUs

### Current Behavior (routes.py lines 3603-3686)
```python
query = db.session.query(WarehouseStock).options(
    joinedload(WarehouseStock.marketplace_listings).joinedload(MarketplaceListing.store)
)
```
- Queries ALL WarehouseStock items
- **NO FILTER** for FBA-linked items
- FBA SKUs appear on Warehouse Stock page and can be SELECTED for push
- Backend will reject, but UI is confusing and misleading

### Push Buttons Available
- "Push Selected" - works on any selected row (including FBA)
- "Push All" - will attempt all (backend filters FBA out)
- "Bulk Adjust" - allows adjusting FBA-linked items (wrong)

## 4. FBA→FBM Switch Detection: NOT IMPLEMENTED

- No current logic to detect when Amazon changes fulfillment_channel from AFN to MFN
- No migration path to archive FBA listing and create FBM listing
- No automatic warehouse_stock record creation for switched items

## 5. MCF Routing (mcf_service.py)

- `OrderFulfillmentRouter.route_order()` checks for FBA availability
- Routes to MCF (FBA) or FBM based on inventory
- Correctly does NOT deduct warehouse stock for MCF orders
- **WORKING AS EXPECTED**

---

## SUMMARY: Issues to Fix

1. **Warehouse Stock page shows FBA SKUs** - must filter them out at query level
2. **No Amazon FBA Stock page** - need read-only view for FBA inventory
3. **No FBA→FBM switch detection** - need sync-time migration
4. **UI badges missing** - Listings page needs clear FBA/FBM source badges
5. **Backend guards exist** but UI allows confusing selection of FBA items

---

*Analysis completed: December 4, 2025*
*Ready for Phase 2: Design*
