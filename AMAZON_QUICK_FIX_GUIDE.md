# Amazon Feed Throttling - Quick Fix Guide

## 🚨 Immediate Solution: Listings PATCH API

When Amazon Feeds are throttled (QuotaExceeded errors), use the Listings API to update quantities immediately. **This bypasses the Feeds quota entirely.**

---

## ✅ Hot-Fix Deployed

### New Management Command: `update_amazon_qty`

Update a single Amazon SKU quantity immediately without using Feeds.

**Usage**:
```bash
python manage.py update_amazon_qty <SKU> <QUANTITY> --store <STORE_NAME> [--marketplace <MARKETPLACE_ID>]
```

**Examples**:
```bash
# Update UK listing (default marketplace)
python manage.py update_amazon_qty AMZ-03-VL-SRU-50g 7 --store BT38

# Update US listing
python manage.py update_amazon_qty AMZ-03-VL-SRU-50g 7 --store BT38 --marketplace ATVPDKIKX0DER

# Update German listing
python manage.py update_amazon_qty AMZ-03-VL-SRU-50g 7 --store BT38 --marketplace A13V1IB3VIYZZH
```

---

## 📋 Supported Marketplaces

| Marketplace | ID | Command Flag |
|-------------|---|--------------|
| UK | A1F83G8C2ARO7P | `--marketplace A1F83G8C2ARO7P` (default) |
| Germany | A13V1IB3VIYZZH | `--marketplace A13V1IB3VIYZZH` |
| France | A1PA6795UKMFR9 | `--marketplace A1PA6795UKMFR9` |
| Spain | A1RKKUPIHCS9HS | `--marketplace A1RKKUPIHCS9HS` |
| Italy | APJ6JRA9NG5V4 | `--marketplace APJ6JRA9NG5V4` |
| US | ATVPDKIKX0DER | `--marketplace ATVPDKIKX0DER` |
| Canada | A2EUQ1WTGCTBG2 | `--marketplace A2EUQ1WTGCTBG2` |

---

## ⚠️ Important Limitations

### MFN Only (Merchant Fulfilled Network)
- ✅ **Works for**: MFN listings (you ship the product)
- ❌ **Does NOT work for**: AFN/FBA listings (Amazon ships the product)
- Amazon controls AFN/FBA quantities - your updates will be ignored

### How to Identify MFN vs AFN/FBA
- **MFN SKUs**: No "-FBA" or "-AFN" suffix
- **AFN/FBA SKUs**: Usually have "-FBA" or "-AFN" in the SKU name
- The command automatically detects and skips AFN/FBA SKUs

---

## 🔍 Verifying SKU Details

Before updating, verify:

### 1. Check Your Store Name
```bash
# List all Amazon stores
python -c "from app import app; from models import Store; \
app.app_context().__enter__(); \
print('\\n'.join([f'{s.name} (ID: {s.id})' for s in Store.query.filter_by(platform='Amazon').all()]))"
```

### 2. Check SKU Exists on Amazon
- Log into Amazon Seller Central
- Go to Inventory → Manage Inventory
- Search for the SKU
- Verify it's **MFN** (not FBA)

### 3. Check Marketplace ID
- In Seller Central, check which marketplace the SKU is listed on
- UK: amazon.co.uk
- US: amazon.com
- etc.

---

## 📖 Step-by-Step: Update AMZ-03-VL-SRU-50g

### Scenario
You need to update `AMZ-03-VL-SRU-50g` to quantity 7 on your BT38 store (UK marketplace).

### Steps

**1. Verify Store Name**
```bash
# List stores
python -c "from app import app; from models import Store; \
app.app_context().__enter__(); \
stores = Store.query.filter_by(platform='Amazon').all(); \
print('Amazon Stores:', [s.name for s in stores])"
```

Expected output: `Amazon Stores: ['BT38']`

**2. Verify SKU Type**
- Check if SKU contains "-FBA" or "-AFN" → If yes, STOP (can't update AFN/FBA)
- `AMZ-03-VL-SRU-50g` → No "-FBA" suffix ✅ MFN (good to update)

**3. Run the Update**
```bash
python manage.py update_amazon_qty AMZ-03-VL-SRU-50g 7 --store BT38
```

**4. Check Output**
- ✅ Success: `✅ Successfully updated AMZ-03-VL-SRU-50g to quantity 7 (Listings API)`
- ❌ Error: Read the error message for troubleshooting

**5. Verify on Amazon**
- Log into Seller Central
- Go to Inventory → Manage Inventory
- Search for `AMZ-03-VL-SRU-50g`
- Check quantity shows 7

---

## 🐛 Troubleshooting

### Error: "Amazon store 'BT38' not found"
**Cause**: Store name doesn't match database  
**Fix**: List stores (see step 1 above) and use exact name

### Error: "SKU appears to be AFN/FBA - quantity controlled by Amazon"
**Cause**: SKU contains "-FBA" or "-AFN"  
**Fix**: Cannot update AFN/FBA quantities via API - Amazon controls these

### Error: "Missing required credentials (refresh_token, client_id)"
**Cause**: Store doesn't have valid Amazon API credentials  
**Fix**: 
1. Go to `/stores` in your dashboard
2. Edit the Amazon store
3. Add/update Amazon API credentials (LWA Client ID, Secret, Refresh Token)

### Error: "Unsupported marketplace ID"
**Cause**: Marketplace ID not recognized  
**Fix**: Use one of the supported marketplace IDs from the table above

### Error: "Listings API error: InvalidInput: ..."
**Cause**: Amazon rejected the update (e.g., SKU doesn't exist, wrong marketplace)  
**Fix**:
1. Verify SKU exists in Seller Central
2. Check you're using the correct marketplace ID
3. Ensure SKU is active (not archived/deleted)

---

## 🔄 When to Use This vs Feeds

| Scenario | Use Listings PATCH | Use Feeds |
|----------|-------------------|-----------|
| **Urgent update (1-50 SKUs)** | ✅ Yes | ❌ No (may be throttled) |
| **Bulk update (100+ SKUs)** | ❌ No (slow) | ✅ Yes (batch in one feed) |
| **Feeds are throttled** | ✅ Yes (bypasses quota) | ❌ No (will fail) |
| **AFN/FBA quantities** | ❌ No (not supported) | ❌ No (Amazon controls) |
| **Regular sync (30s cycle)** | ❌ No (inefficient) | ✅ Yes (batched) |

**Rule of Thumb**:
- **1-50 urgent MFN SKUs** → Use Listings PATCH
- **100+ SKUs or regular sync** → Use Feeds (with batching)

---

## 📊 API Quota Information

### Listings Items API
- **Quota**: Separate from Feeds API
- **Rate Limit**: ~200 requests per second
- **Best For**: Small batch urgent updates

### Feeds API  
- **Quota**: ~100 feed creations per hour
- **Rate Limit**: 1-2 feeds per minute
- **Best For**: Bulk updates (batch many SKUs)

**Key Insight**: When Feeds quota is exhausted, Listings API still works!

---

## 🚀 Next Steps

### For Immediate Needs
Use the `update_amazon_qty` command for urgent updates right now.

### For Long-Term Fix
The feed batching system is being implemented to prevent future throttling:
1. **Regional Serialization** ✅ Deployed - Prevents parallel feed creation
2. **Exponential Backoff** ✅ Deployed - Retries on QuotaExceeded
3. **Batching** 🚧 In Progress - Multiple SKUs in one feed
4. **Guard-Rails** 🚧 Pending - Skip AFN/inactive listings

See `AMAZON_FEED_THROTTLING_FIX.md` for full implementation details.

---

## 📞 Support

### Command Not Working?
1. Check you're in the project directory
2. Verify Flask app context is available
3. Check logs: `tail -f /tmp/logs/Start_application_*.log`

### SKU Still Not Updating?
1. Wait 5-10 minutes (Amazon propagation delay)
2. Check Amazon Seller Central directly
3. Verify no suppressed listing warnings

### Need Bulk Updates?
- Use the Listings PATCH for up to 50 SKUs
- For 100+ SKUs, wait for feed batching implementation
- Or manually batch into groups of 50

---

**Quick Reference**:
```bash
# Update quantity immediately (bypasses Feeds quota)
python manage.py update_amazon_qty <SKU> <QTY> --store <STORE> [--marketplace <MKT_ID>]

# Example
python manage.py update_amazon_qty AMZ-03-VL-SRU-50g 7 --store BT38
```

✅ **Status**: Hot-fix deployed and ready to use!
