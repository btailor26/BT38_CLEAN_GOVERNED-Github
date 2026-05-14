# Amazon SP-API Feed Throttling Fix - Implementation Status

## Problem Statement

**Current Issue**: Creating one feed per SKU triggers Amazon's QuotaExceeded error  
**Impact**: 302 SKU changes =  302 separate feeds → API quota exhausted  
**Result**: Inventory updates fail, listings out of sync

## Solution Overview

Implement the recommended Amazon SP-API best practices:
1. **Exponential Backoff**: Retry on QuotaExceeded with jitter
2. **Regional Serialization**: One feed at a time per region (EU/NA/FE)
3. **Batch Processing**: Multiple SKUs in one feed (not 1 SKU per feed)
4. **Listings PATCH Fallback**: For urgent MFN updates

## ✅ Completed (Phase 1)

### 1. Infrastructure Added (`amazon_service.py`)

#### Regional Feed Locks
```python
FEED_LOCKS = {
    "eu": Lock(),
    "na": Lock(),
    "fe": Lock(),
}
```
Prevents parallel feed creation for the same region.

#### QuotaExceededError Class
```python
class QuotaExceededError(Exception):
    """Raised when Amazon SP-API returns QuotaExceeded error"""
    pass
```

#### Exponential Backoff with Jitter
```python
def _sleep_with_jitter(base: float, attempt: int, cap: float = 120.0):
    """Exponential backoff with full jitter"""
    delay = min(cap, base * (2 ** attempt))
    actual_delay = random.uniform(0, delay)
    time.sleep(actual_delay)
```

#### Marketplace → Region Mapping
```python
def region_from_marketplace(marketplace_id: str) -> str:
    """Map marketplace ID to region (eu/na/fe)"""
    EU_MARKETPLACES = {"A1F83G8C2ARO7P", ...}  # UK, DE, FR, ES, IT, etc.
    NA_MARKETPLACES = {"ATVPDKIKX0DER", ...}   # US, CA, MX
    # Returns: "eu", "na", or "fe"
```

### 2. Core Methods Added

#### `_create_feed_with_backoff()`
**Purpose**: Wrap create_feed() with retry logic  
**Features**:
- Detects QuotaExceeded errors
- Retries up to 6 times with exponential backoff
- Non-quota errors fail immediately (no retry loop)
- Logs each attempt

**Usage**:
```python
payload = {
    'feed_type': 'POST_INVENTORY_AVAILABILITY_DATA',
    'marketplace_ids': [marketplace_id],
    'input_feed_document_id': feed_doc_id
}
response = self._create_feed_with_backoff(feeds_client, payload)
```

#### `_generate_batched_inventory_feed_xml()`
**Purpose**: Generate XML for multiple SKUs in one feed  
**Features**:
- Takes list of (sku, quantity) tuples
- Creates one XML with multiple <Message> elements
- Each SKU gets unique MessageID

**Usage**:
```python
items = [
    ("SKU-001", 10),
    ("SKU-002", 5),
    ("SKU-003", 0)
]
xml = self._generate_batched_inventory_feed_xml(items, seller_id)
```

## 🚧 Remaining Work (Phase 2)

### 3. Update Feed Creation Logic

**Current (WRONG)**:
```python
# One feed per SKU - triggers quota!
for item in changed_items:
    xml = self._generate_inventory_feed_xml(item)
    create_feed(xml)  # 100 SKUs = 100 feeds!
```

**Target (RIGHT)**:
```python
# Batch multiple SKUs into one feed
batch_size = 100  # or 500, 1000
for chunk in chunks(changed_items, batch_size):
    items = [(sku, qty) for sku, qty in chunk]
    xml = self._generate_batched_inventory_feed_xml(items, seller_id)
    
    # Use regional lock + backoff
    region = region_from_marketplace(marketplace_id)
    with FEED_LOCKS[region]:
        response = self._create_feed_with_backoff(feeds_client, payload)
```

### 4. Update smart_push_service.py

**Needed**: Batch pending Amazon changes instead of pushing one-by-one  
**Location**: `smart_push_service.py` around line 200-300

**Current Flow**:
```
For each MarketplaceListing:
    if needs_push:
        amazon_service.sync_inventory_to_amazon(item)  # One feed!
```

**Target Flow**:
```
pending_amazon_listings = [listings that need push]
batch_by_store_and_marketplace(pending_amazon_listings)

For each batch:
    items = [(listing.external_sku, warehouse_qty) for listing in batch]
    amazon_service.batch_update_inventory(store, marketplace_id, items)
```

### 5. Add Listings PATCH Fallback

**Purpose**: For urgent MFN SKUs when Feeds API is throttled  
**API**: `/listings/2021-08-01/items/{sellerId}/{sku}`  
**Quota**: Separate from Feeds (doesn't count against feed limit)

**Implementation Needed**:
```python
def update_listing_quantity_patch(self, store: Store, sku: str, quantity: int, marketplace_id: str):
    """
    Update quantity via Listings PATCH API (MFN only, bypasses Feeds quota)
    Use for urgent updates when Feeds API is throttled
    """
    try:
        listings_client = ListingsItems(credentials=..., marketplace=...)
        
        response = listings_client.patch_listings_item(
            sellerId=seller_id,
            sku=sku,
            marketplaceIds=[marketplace_id],
            body={
                "productType": "PRODUCT",
                "patches": [{
                    "op": "replace",
                    "path": "/attributes/fulfillment_availability",
                    "value": [{
                        "fulfillment_channel_code": "DEFAULT",
                        "quantity": quantity
                    }]
                }]
            }
        )
        return True, "Quantity updated via Listings API"
    except Exception as e:
        return False, str(e)
```

### 6. Update FeedStatus Model

**Current**: Tracks one SKU per feed  
**Needed**: Track multiple SKUs per feed

**Migration Needed**:
```python
# Add new fields to FeedStatus
skus_in_feed = db.Column(db.JSON)  # ["SKU-001", "SKU-002", ...]
sku_count = db.Column(db.Integer, default=1)

# Or keep separate tracking table
class FeedSkuStatus(db.Model):
    feed_id = db.Column(db.String, db.ForeignKey('feed_status.feed_id'))
    sku = db.Column(db.String)
    quantity_pushed = db.Column(db.Integer)
    success = db.Column(db.Boolean)
```

### 7. Add Guard-Rails

**Needed in smart_push_service.py**:

```python
def should_push_to_amazon(listing: MarketplaceListing) -> Tuple[bool, str]:
    """Determine if listing should be pushed to Amazon"""
    
    # Skip AFN/FBA (Amazon controls quantity)
    if listing.external_sku and '-FBA' in listing.external_sku:
        return False, "AFN/FBA listing - quantity controlled by Amazon"
    
    # Skip listings without price
    if not listing.price or listing.price <= 0:
        return False, "No valid price - inactive listing"
    
    # Skip if no SKU mapping
    if not listing.warehouse_stock:
        return False, "No warehouse stock linked"
    
    # Skip if recently pushed (cooldown)
    if listing.last_push_at:
        minutes_since = (datetime.utcnow() - listing.last_push_at).total_seconds() / 60
        if minutes_since < 5:  # 5-minute cooldown
            return False, f"Pushed {minutes_since:.1f}min ago - cooldown active"
    
    return True, "OK to push"
```

## Testing Plan

### Phase 1: Dry-Run Simulation
```bash
# Test backoff logic with mock quota errors
python -m pytest tests/test_amazon_throttling.py

# Verify regional locks work
python -m pytest tests/test_regional_serialization.py
```

### Phase 2: Staging Test
```bash
# Create test feed with 10 SKUs
python manage.py test-amazon-batch --skus 10

# Monitor for QuotaExceeded and backoff behavior
tail -f /tmp/logs/Start_application_*.log | grep -i "quota\|backoff"
```

### Phase 3: Production Rollout
1. **Week 1**: Deploy with batch_size=10 (conservative)
2. **Week 2**: Increase to batch_size=50
3. **Week 3**: Increase to batch_size=100
4. **Monitor**: Watch for QuotaExceeded in logs

## Expected Impact

### Before (Current)
- **Feeds Created**: 302 per sync cycle (one per SKU)
- **API Calls**: 302 create_feed() calls
- **Result**: QuotaExceeded after ~50-100 feeds
- **Sync Success Rate**: ~30%

### After (With Fix)
- **Feeds Created**: 3-4 per sync cycle (batched)
- **API Calls**: 3-4 create_feed() calls
- **Result**: Well under quota
- **Sync Success Rate**: ~95%+

### Quota Math
Amazon SP-API Feeds quota (typical):
- **Limit**: ~100 feed creations per hour
- **Current Usage**: 302 feeds = 3 hours of quota in 30 seconds!
- **With Batching**: 3 feeds = 3% of hourly quota

## Configuration Recommendations

### Batch Sizes
```python
AMAZON_FEED_BATCH_SIZES = {
    "conservative": 10,   # Start here
    "moderate": 50,       # After 1 week
    "aggressive": 100,    # After 2 weeks
    "maximum": 500,       # For bulk operations
}
```

### Backoff Settings
```python
FEED_RETRY_CONFIG = {
    "max_attempts": 6,      # Up to 6 retries
    "base_delay": 3.0,      # Start with 3 seconds
    "max_delay": 120.0,     # Cap at 2 minutes
}
```

### Sync Cadence
```python
AMAZON_SYNC_INTERVALS = {
    "normal": 60,          # 1 feed per minute (current: 30s)
    "throttled": 180,      # 1 feed per 3 minutes (if quota issues)
    "recovery": 300,       # 1 feed per 5 minutes (after quota exceeded)
}
```

## Files Modified

| File | Status | Changes |
|------|--------|---------|
| `amazon_service.py` | ✅ Partial | Added infrastructure + core methods |
| `smart_push_service.py` | ⏳ Pending | Need to add batching logic |
| `models.py` | ⏳ Pending | Update FeedStatus for multi-SKU tracking |
| `sync_service.py` | ⏳ Pending | Adjust sync cadence |

## Next Steps

### Option A: Complete Full Implementation (Recommended)
1. Update smart_push_service.py with batching
2. Modify sync_inventory_to_amazon() to use _create_feed_with_backoff
3. Add Listings PATCH fallback
4. Update FeedStatus model
5. Test with 10-SKU batch
6. Deploy to production

**Estimated Time**: 2-3 hours  
**Risk**: Low (backward compatible)

### Option B: Minimal Quick Fix (Fastest)
1. Just wrap existing create_feed() with _create_feed_with_backoff()
2. Add regional lock around feed creation
3. Increase sync interval from 30s to 60s

**Estimated Time**: 30 minutes  
**Risk**: Medium (still creates many feeds, just with backoff)

### Option C: Gradual Rollout
1. Deploy infrastructure changes now (✅ done)
2. Week 1: Add backoff wrapper
3. Week 2: Add batching for Amazon only
4. Week 3: Full rollout with monitoring

**Estimated Time**: 3 weeks  
**Risk**: Very Low (staged approach)

## Monitoring

### Key Metrics to Track
```sql
-- Feeds created per hour
SELECT 
    date_trunc('hour', submitted_at) as hour,
    COUNT(*) as feed_count,
    COUNT(DISTINCT sku) as sku_count,
    AVG(EXTRACT(EPOCH FROM (processing_ended_at - submitted_at))) as avg_duration_seconds
FROM feed_status
WHERE submitted_at > NOW() - INTERVAL '24 hours'
GROUP BY hour
ORDER BY hour DESC;

-- QuotaExceeded errors
SELECT COUNT(*) as quota_errors
FROM feed_status
WHERE error_message LIKE '%QuotaExceeded%'
AND submitted_at > NOW() - INTERVAL '24 hours';

-- Success rate
SELECT 
    processing_status,
    COUNT(*) as count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 2) as percentage
FROM feed_status
WHERE submitted_at > NOW() - INTERVAL '24 hours'
GROUP BY processing_status;
```

## Support

If QuotaExceeded persists after implementation:
1. Check batch size (reduce to 10)
2. Increase sync interval (60s → 120s)
3. Enable Listings PATCH fallback for urgent SKUs
4. Contact Amazon Seller Support to request quota increase

---

**Status**: Phase 1 Complete ✅  
**Next Action**: Choose Option A, B, or C above  
**Blocked By**: Decision on implementation approach
