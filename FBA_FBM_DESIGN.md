# Phase 2: FBA/FBM Separation Design Document

## Design Overview

This document outlines the strict separation between FBA (read-only) and FBM (warehouse-controlled) inventory.

---

## 1. Warehouse Stock Page (FBM Only)

### Data Source Change
```python
# BEFORE: Shows all WarehouseStock items
query = db.session.query(WarehouseStock)

# AFTER: Filter out items linked to FBA stores
query = db.session.query(WarehouseStock).filter(
    ~WarehouseStock.id.in_(
        db.session.query(MarketplaceListing.warehouse_stock_id)
        .join(Store, MarketplaceListing.store_id == Store.id)
        .filter(Store.platform == 'AmazonFBA')
        .distinct()
    )
)
```

### Bulk Actions
- "Push Selected" → Operates only on FBM-linked items (already filtered)
- "Push All" → Only processes FBM items (already filtered)
- "Bulk Adjust" → Only affects warehouse-controlled stock (already filtered)
- "Select All" → Only selects visible (FBM) items

### Statistics
- Update stats to exclude FBA-linked items
- Show only warehouse-controllable inventory

---

## 2. New Page: Amazon FBA Stock (Read-Only)

### Route
```
/amazon_fba_stock
```

### Table Columns
| Column | Description |
|--------|-------------|
| SKU | Seller SKU |
| Title | Product name |
| ASIN | Amazon ASIN |
| FBA Qty | Sellable quantity (Amazon-controlled) |
| Reserved | Reserved quantity |
| Inbound | Inbound shipping quantity |
| Last Sync | Last updated timestamp |
| Actions | View, Open Amazon, Create MCF Order |

### Page Header
- Clear subtitle: "Read-only FBA inventory. Stock is managed by Amazon. Use MCF for fulfillment."
- FBA badge prominently displayed
- NO push buttons anywhere on page

### Allowed Actions
1. View listing details
2. Open on Amazon (external link)
3. Create MCF Order (for multi-channel fulfillment)
4. View sync history

### Blocked Actions (not shown)
- Push stock
- Adjust quantity
- Bulk adjust

---

## 3. Listings Page Badges

### Badge Display
Each listing shows a clear source badge:

```html
<!-- FBA Listing -->
<span class="badge bg-info">
    <i data-feather="box"></i> Source: Amazon FBA
</span>

<!-- FBM Listing -->
<span class="badge bg-primary">
    <i data-feather="package"></i> Source: Warehouse (FBM)
</span>
```

### Filter Options
Add platform filter dropdown:
- All Listings
- Amazon FBA Only
- Amazon FBM Only
- eBay
- (other platforms)

### Dual-Listing Products
If a product has both FBA and FBM listings:
- Show as separate rows (not merged)
- Each with its own clear badge
- Different quantities displayed for each

---

## 4. Central FBA Push Guard

### New Helper Function
Create `is_fba_protected(warehouse_stock_id)` helper:

```python
def is_fba_protected(warehouse_stock_id: int) -> Tuple[bool, str]:
    """
    Check if a warehouse stock item is linked to FBA and should be protected.
    
    Returns:
        (is_protected, reason) - True if push should be blocked
    """
    from models import MarketplaceListing, Store
    
    fba_listing = MarketplaceListing.query.join(Store).filter(
        MarketplaceListing.warehouse_stock_id == warehouse_stock_id,
        Store.platform == 'AmazonFBA'
    ).first()
    
    if fba_listing:
        return True, "FBA listings are read-only; stock is managed by Amazon."
    
    return False, ""
```

### Apply to All Push Entry Points
1. `/push_stock/<item_id>` - Check before enqueueing
2. `/push_stock_bulk` - Filter out protected items
3. `/push_stock_all` - Exclude protected items
4. `SmartPushService` methods - Already protected, keep existing
5. `SyncDispatcher` - Already protected, keep existing

### Standard Error Response
```json
{
    "error": "FBA listings are read-only; stock is managed by Amazon.",
    "blocked_skus": ["SKU1", "SKU2"]
}
```

---

## 5. FBA → FBM Switch Detection & Migration

### During Amazon Sync

When syncing Amazon listings, check `fulfillment_channel`:
- `AFN` = FBA (Fulfillment by Amazon)
- `MFN` = FBM (Merchant Fulfilled Network)

### Detection Logic
```python
def check_fulfillment_switch(listing_data, existing_listing):
    current_channel = listing_data.get('fulfillment_channel', 'MFN')
    stored_channel = existing_listing.amazon_fulfillment_channel
    
    if stored_channel == 'AFN' and current_channel == 'MFN':
        return 'FBA_TO_FBM'
    elif stored_channel == 'MFN' and current_channel == 'AFN':
        return 'FBM_TO_FBA'
    return None
```

### FBA → FBM Migration Steps
1. **Archive FBA Record**:
   - Set `is_active = False` on AmazonFBAListing
   - Set `archived_at = datetime.utcnow()`
   - Set `archive_reason = 'fulfillment_switch_to_fbm'`

2. **Create/Link FBM Listing**:
   - Create new AmazonFBMListing record
   - Link to same warehouse_stock_id
   - Set initial quantity = 0 (requires manual stock count)

3. **Ensure Warehouse Stock Exists**:
   - If no WarehouseStock for this SKU, create one with qty = 0
   - Log creation for admin review

4. **Update Fulfillment Routing**:
   - New orders for this SKU use FBM path (warehouse deduction)
   - Profit calculator uses FBM fee model

5. **Log the Switch**:
   - Create SystemLog entry with type = 'fulfillment_switch'
   - Include SKU, ASIN, old/new channel, timestamp

### UI Notification
On Listings page, show banner for recently switched items:
```html
<div class="alert alert-info">
    <i data-feather="refresh-cw"></i>
    Fulfillment changed on Amazon: <strong>SKU123</strong> is now FBM (warehouse).
    Please verify stock levels.
</div>
```

---

## 6. Implementation Order

1. **Backend safety guard** (central helper function)
2. **Warehouse Stock query filter** (exclude FBA)
3. **Amazon FBA Stock page** (new route + template)
4. **Listings page badges** (FBA/FBM indicators)
5. **FBA→FBM detection** (sync-time migration)
6. **Test all paths**

---

*Design document completed: December 4, 2025*
*Ready for Phase 3: Implementation*
