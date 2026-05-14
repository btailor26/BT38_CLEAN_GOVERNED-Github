# eBay Quantity-Only Push - Complete Guide

**Status**: Implemented and Production-Ready ✅  
**Date**: October 31, 2025

---

## 🎯 Problem & Solution

### The Problem
eBay's ReviseFixedPriceItem API triggers **full category aspect validation** whenever called, even if you're only updating quantity. This causes pushes to fail with errors like:

```
Error Code: 21919303
"The item specific 'Author' is missing. Add Author to continue."
```

**Impact**: Quantity pushes fail due to unrelated metadata issues

### The Solution
Use **quantity-only APIs** that bypass aspect validation:

✅ **For Quantity Updates**: `ReviseInventoryStatus` (Trading API)  
✅ **For Price Updates**: `ReviseInventoryStatus` (can include price)  
❌ **For Metadata Updates**: `ReviseFixedPriceItem` (triggers validation)

---

## ✅ Current Implementation Status

### What's Already Working

**1. Quantity Updates Use ReviseInventoryStatus**
- File: `ebay_service.py`, method: `update_listing_quantity()` (lines 959-1045)
- ✅ Already using `ReviseInventoryStatus`
- ✅ Bypasses aspect validation
- ✅ Works for both single listings and variations

**2. Smart Push Uses Quantity-Only Method**
- File: `smart_push_service.py`, line 133
- ✅ Calls `update_listing_quantity()` for eBay pushes
- ✅ Includes SKU for variation items
- ✅ Never triggers aspect validation for quantity changes

**3. Preflight Validation Now Available** ✅ NEW!
- File: `ebay_service.py`, methods: `validate_required_specifics()`, `preflight_check()`
- ✅ Detects missing required ItemSpecifics before push
- ✅ Category-specific validation (Books → Author required)
- ✅ Clear error messages with actionable guidance

---

## 🚀 How to Use

### 1. Update Quantity for a Single eBay Listing

**Direct Python Usage**:
```python
from ebay_service import eBayAPIService
from models import Store

ebay_service = eBayAPIService()
store = Store.query.filter_by(name='beatsoutlet', platform='eBay').first()

# Update quantity (bypasses aspect validation)
success, message = ebay_service.update_listing_quantity(
    item_id="116825828130",
    quantity=7,
    sku=None  # Include SKU only for variation items
)

if success:
    print(f"✅ {message}")
else:
    print(f"❌ {message}")
```

**What Happens**:
- Uses `ReviseInventoryStatus` API call
- Updates quantity only
- Does NOT validate Author, Language, or other ItemSpecifics
- Fast and reliable

---

### 2. Preflight Validation (Detect Issues Before Push)

**CLI Command**:
```bash
# Check a single listing
python manage.py ebay_preflight 116825828130 --store beatsoutlet

# Check multiple listings
python manage.py ebay_preflight 116825828130 115323385386 125236609033 --store beatsoutlet
```

**Example Output**:
```
🔍 Running preflight validation on 3 listing(s)...

✅ 116825828130: OK - All required specifics present
❌ 115323385386: Missing required ItemSpecifics: author
   Missing: author
✅ 125236609033: OK - All required specifics present

📊 Summary: 2 passed, 1 blocked
```

**Python Usage**:
```python
from ebay_service import eBayAPIService

ebay_service = eBayAPIService()

# Run preflight check
can_push, reason, missing = ebay_service.preflight_check(
    store=store,
    item_id="116825828130"
)

if not can_push:
    print(f"❌ Cannot push: {reason}")
    print(f"Missing: {', '.join(missing)}")
    # Block push or mark listing for manual review
else:
    print(f"✅ Safe to push")
    # Proceed with quantity update
```

---

## 📋 API Comparison

| API Endpoint | Use Case | Aspect Validation | Speed | Use For |
|-------------|----------|-------------------|-------|---------|
| **ReviseInventoryStatus** | Qty/Price only | ❌ No | Fast | **Stock updates** |
| **ReviseFixedPriceItem** | Full listing edit | ✅ Yes | Slow | **Metadata fixes** |
| **Listings Items API (REST)** | Modern alternative | Depends | Fast | Future migration |

---

## 🔍 How Preflight Validation Works

### Category Detection
The system automatically detects if a listing requires specific ItemSpecifics based on:

**Books Category Indicators**:
- ItemSpecific keys: `ISBN`, `Publication Year`, `Publisher`
- If detected → Validates `Author` is present

**Extensible for Other Categories**:
```python
# In ebay_service.py, line 17-21
REQUIRED_SPECIFICS_BY_CATEGORY = {
    'books': ['author'],
    'media': ['format'],  # Can extend
    'electronics': ['brand', 'model'],  # Can extend
}
```

### Validation Logic
1. Fetches item details via `GetItem` API
2. Extracts all ItemSpecifics
3. Normalizes keys (case-insensitive)
4. Checks if required specifics exist and have values
5. Returns list of missing specifics

---

## 🛠️ Integration into Smart Push

The preflight validation can be integrated into the automated push service:

**Proposed Enhancement** (Optional):
```python
# In smart_push_service.py, before pushing

# Run preflight check
can_push, reason, missing = ebay_service.preflight_check(
    store=listing.store,
    item_id=listing.external_listing_id
)

if not can_push:
    # Block listing from push
    listing.push_state = 'blocked'
    listing.blocked_reason = f"Missing ItemSpecifics: {', '.join(missing)}"
    listing.push_message = "Fix in eBay Seller Hub, then re-import to unblock"
    db.session.commit()
    
    self.logger.warning(f"⚠️ Blocked {listing.external_listing_id}: {reason}")
    return  # Skip this listing
    
# Preflight passed - safe to push
success, message = ebay_service.update_listing_quantity(
    item_id=listing.external_listing_id,
    quantity=warehouse_qty,
    sku=listing.external_sku if listing.listing_type == 'variation_child' else None
)
```

**Benefits**:
- Detects issues before they cause push failures
- Provides actionable error messages
- Allows quantity pushes to continue for valid listings

---

## 🔄 Recommended Workflow

### For Automated Sync

```mermaid
graph TD
    A[Warehouse Qty Changed] --> B{Need to Push to eBay?}
    B -->|Yes| C[Run Preflight Check]
    C -->|PASS| D[Push via ReviseInventoryStatus]
    C -->|BLOCKED| E[Mark as Blocked + Log Reason]
    E --> F[Continue with Other Listings]
    D --> G[Update last_push_at]
    B -->|No| H[Skip]
```

### For Manual Fixes

1. **Identify Blocked Listings**:
   ```bash
   python manage.py ebay_preflight 116825828130 --store beatsoutlet
   ```

2. **If Missing Author** (or other specifics):
   - Option A: Fix in eBay Seller Hub manually
   - Option B: Add auto-repair to codebase (see below)

3. **Re-import Listing**:
   - Triggers fresh import from eBay
   - Captures newly added ItemSpecifics
   - Auto-unblocks if validation now passes

4. **Push Proceeds Automatically**:
   - Next sync cycle detects unblocked listing
   - Pushes quantity via ReviseInventoryStatus

---

## 🧰 Optional: Auto-Repair Missing Specifics

**When to Use**:
- You have Author/Publisher data in your warehouse
- Want to automatically fix missing specifics

**Implementation** (Not yet added - can be added if needed):
```python
def auto_repair_missing_specifics(
    self,
    store: Store,
    item_id: str,
    missing_specifics: Dict[str, str]
) -> Tuple[bool, str]:
    """
    Automatically add missing ItemSpecifics if we have the data
    
    Args:
        store: eBay store
        item_id: eBay ItemID
        missing_specifics: Dict of {specific_name: value} to add
        
    Example:
        missing = {'author': 'J.K. Rowling', 'publisher': 'Bloomsbury'}
        success, msg = service.auto_repair_missing_specifics(store, item_id, missing)
    """
    # Build ItemSpecifics XML
    specifics_xml = ""
    for name, value in missing_specifics.items():
        specifics_xml += f"""
        <NameValueList>
            <Name>{name}</Name>
            <Value>{value}</Value>
        </NameValueList>"""
    
    xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
<ReviseFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
    <RequesterCredentials>
        <eBayAuthToken>{access_token}</eBayAuthToken>
    </RequesterCredentials>
    <Item>
        <ItemID>{item_id}</ItemID>
        <ItemSpecifics>{specifics_xml}</ItemSpecifics>
    </Item>
</ReviseFixedPriceItemRequest>"""
    
    # Execute API call
    # ... (similar to update_listing_price)
```

---

## 📊 Testing Results

### Test Case 1: Quantity-Only Push
```bash
# Listing: 116825828130 (AMZ-03-VL-SRU-50g)
# Expected: Success (using ReviseInventoryStatus)
```

**Current Status**: ✅ Already using correct API

### Test Case 2: Preflight Validation
```bash
python manage.py ebay_preflight 116825828130 --store beatsoutlet
```

**Expected Output**:
- If missing Author → ❌ BLOCKED: Missing required ItemSpecifics: author
- If Author present → ✅ OK - All required specifics present

---

## 🎓 Key Learnings

### Why This Matters

1. **Separation of Concerns**:
   - Quantity updates ≠ Metadata updates
   - Use different APIs for different purposes

2. **eBay API Behavior**:
   - `ReviseFixedPriceItem` = Full validation (slow, can fail)
   - `ReviseInventoryStatus` = Qty/Price only (fast, no validation)

3. **Proactive Detection**:
   - Preflight validation catches issues before push
   - Prevents cascading failures across multiple listings

4. **User Experience**:
   - Clear, actionable error messages
   - "Fix in Seller Hub → Re-import → Auto-unblock"
   - No developer intervention needed

---

## 📝 Configuration

### Category Rules (ebay_service.py, lines 17-21)

Extend category-specific validation rules as needed:

```python
REQUIRED_SPECIFICS_BY_CATEGORY = {
    'books': ['author'],
    'media': ['format'],
    'electronics': ['brand', 'model'],
    'clothing': ['size', 'color'],
    # Add more as patterns emerge
}
```

### Auto-Detection Patterns (ebay_service.py, lines 277-278)

Books detection based on ItemSpecific keys:
```python
has_book_indicators = any(
    key.lower() in ['isbn', 'publication year', 'publisher'] 
    for key in item_specifics.keys()
)
```

Extend for other categories:
```python
has_electronics = any(
    key.lower() in ['brand', 'model number', 'upc'] 
    for key in item_specifics.keys()
)
```

---

## 🐛 Troubleshooting

### Issue: "Item specific 'Author' is missing"
**Diagnosis**: Listing is in Books category but missing Author  
**Fix**: 
1. Run preflight: `python manage.py ebay_preflight <item_id> --store beatsoutlet`
2. If blocked: Fix in eBay Seller Hub
3. Re-import listing (or wait for next sync)
4. Preflight passes → Push succeeds

### Issue: Preflight always passes but pushes still fail
**Diagnosis**: Category detection not working  
**Fix**:
1. Check item_specifics returned by `get_item_details()`
2. Verify category indicators are present
3. Extend detection logic if needed

### Issue: Want to auto-fix missing Author
**Solution**: Implement `auto_repair_missing_specifics()` method (see above)

---

## 🚀 Next Steps (Optional Enhancements)

### 1. Auto-Repair Integration
- Add `auto_repair_missing_specifics()` method
- Integrate into smart_push_service
- Fetch Author from warehouse/catalog if available

### 2. Dashboard Integration
- Add "Run Preflight" button to listings page
- Show blocked listings with missing specifics
- One-click "Fix in Seller Hub" links

### 3. Category Detection Enhancement
- Use GetItem's `PrimaryCategory.CategoryID` instead of heuristics
- Fetch category-specific requirements from eBay's API
- Cache category rules for performance

### 4. Batch Preflight Validation
- Run preflight on all listings during import
- Mark potentially problematic listings early
- Generate CSV report of issues

---

## 📞 Support

### Commands Reference

```bash
# Run preflight validation
python manage.py ebay_preflight <item_id> --store <store_name>

# Example
python manage.py ebay_preflight 116825828130 --store beatsoutlet

# Multiple listings
python manage.py ebay_preflight 116825828130 115323385386 --store beatsoutlet
```

### Python API Reference

```python
from ebay_service import eBayAPIService

service = eBayAPIService()

# Preflight check
can_push, reason, missing = service.preflight_check(store, item_id)

# Validate specifics
is_valid, missing = service.validate_required_specifics(item_specifics, category="books")

# Update quantity (safe)
success, message = service.update_listing_quantity(item_id, quantity, sku=None)
```

---

## ✅ Summary

| Feature | Status | Details |
|---------|--------|---------|
| **Quantity-Only API** | ✅ Implemented | Uses ReviseInventoryStatus |
| **Price-Only API** | ✅ Implemented | Uses ReviseInventoryStatus with price |
| **Preflight Validation** | ✅ Implemented | Detects missing specifics |
| **CLI Command** | ✅ Implemented | `python manage.py ebay_preflight` |
| **Books Category** | ✅ Supported | Validates Author requirement |
| **Auto-Repair** | ⏳ Optional | Can be added if needed |
| **Dashboard UI** | ⏳ Future | Can add "Run Preflight" button |

---

**Status**: Production-ready for quantity-only pushes with preflight validation  
**Impact**: Prevents aspect validation errors, enables reliable eBay stock sync  
**Documentation**: Complete with examples and troubleshooting
