# eBay Price Remediation Runbook

## Overview

This runbook describes the procedure for fixing eBay listings with prices below the marketplace minimum (£0.99). The remediation script updates listing prices via the eBay Trading API and tracks all changes in a CSV report.

## Prerequisites

Before running the remediation script, ensure:

1. **Valid eBay OAuth Tokens**: Store must have valid `access_token` or `user_token` in the `api_key` JSON field
2. **Active Store Connection**: eBay store must be active and syncing (check `/stores` page)
3. **Proper Permissions**: eBay API credentials must have `ReviseFixedPriceItem` permissions
4. **Backup**: Database backup recommended before running in `--apply` mode

## eBay Minimum Price Rules

- **UK Site (Site ID 3)**: Minimum £0.99
- **US Site (Site ID 0)**: Minimum $0.99
- **Other Sites**: Check eBay's minimum pricing policy for your marketplace

## Usage

### Dry Run Mode (Recommended First Step)

**Always start with a dry run** to see what would be changed:

```bash
python manage.py fix_ebay_prices --dry-run
```

This will:
- ✅ Find all eBay listings with prices < £0.99
- ✅ Report what would be changed (no actual updates)
- ✅ Generate a CSV report in `reports/ebay_price_fix_dry_run_YYYYMMDD_HHMMSS.csv`
- ✅ Show summary statistics

### Apply Mode (Actually Update Prices)

After reviewing the dry run results, apply the changes:

```bash
python manage.py fix_ebay_prices --apply
```

This will:
- ✅ Update eBay listing prices via Trading API
- ✅ Update local `MarketplaceListing.price` in database
- ✅ Reset `push_state` to 'active' (unblock listings)
- ✅ Reset `consecutive_failures` to 0
- ✅ Log all changes to `SyncLog` table
- ✅ Generate CSV report in `reports/ebay_price_fix_applied_YYYYMMDD_HHMMSS.csv`

### Advanced Options

#### Filter by Store

Fix prices for a specific store only:

```bash
python manage.py fix_ebay_prices --apply --store beatsoutlet
```

#### Custom Minimum Price

Set a custom minimum price (default is £0.99):

```bash
python manage.py fix_ebay_prices --apply --min 1.29
```

#### Batch Size

Control API rate limiting by adjusting batch size (default: 20):

```bash
python manage.py fix_ebay_prices --apply --batch-size 10
```

## Example Workflow

### Step 1: Investigate the Issue

Check how many listings are affected:

```bash
python manage.py fix_ebay_prices --dry-run
```

**Expected Output:**
```
INFO:scripts.fix_ebay_prices:Found 68 eBay listings with price < £0.99
INFO:scripts.fix_ebay_prices:[DRY-RUN] Would update 123456789 (SKU: BEAT-001): £0.00 → £0.99
...
INFO:scripts.fix_ebay_prices:================================================================================
INFO:scripts.fix_ebay_prices:eBay Price Remediation Summary (DRY-RUN)
INFO:scripts.fix_ebay_prices:================================================================================
INFO:scripts.fix_ebay_prices:Total listings found: 68
INFO:scripts.fix_ebay_prices:Successfully updated: 0
INFO:scripts.fix_ebay_prices:Errors: 0
INFO:scripts.fix_ebay_prices:Skipped (dry-run): 68
INFO:scripts.fix_ebay_prices:CSV report: reports/ebay_price_fix_dry_run_20250131_143022.csv
INFO:scripts.fix_ebay_prices:================================================================================
```

### Step 2: Review the CSV Report

Open the generated CSV file and review the changes:

```csv
itemId,sku,store,oldPrice,newPrice,changedAtUTC,status
123456789,BEAT-001,beatsoutlet,0.00,0.99,2025-01-31T14:30:22Z,dry-run
123456790,BEAT-002,beatsoutlet,0.00,0.99,2025-01-31T14:30:22Z,dry-run
```

### Step 3: Apply the Changes

If the dry run looks correct, apply the changes:

```bash
python manage.py fix_ebay_prices --apply
```

**Expected Output:**
```
INFO:scripts.fix_ebay_prices:Updating 123456789 (SKU: BEAT-001): £0.00 → £0.99
INFO:ebay_service:✅ Successfully updated eBay listing 123456789 price to £0.99
INFO:scripts.fix_ebay_prices:✅ Successfully updated 123456789
...
INFO:scripts.fix_ebay_prices:================================================================================
INFO:scripts.fix_ebay_prices:eBay Price Remediation Summary (APPLIED)
INFO:scripts.fix_ebay_prices:================================================================================
INFO:scripts.fix_ebay_prices:Total listings found: 68
INFO:scripts.fix_ebay_prices:Successfully updated: 68
INFO:scripts.fix_ebay_prices:Errors: 0
INFO:scripts.fix_ebay_prices:Skipped (dry-run): 0
INFO:scripts.fix_ebay_prices:CSV report: reports/ebay_price_fix_applied_20250131_143045.csv
INFO:scripts.fix_ebay_prices:================================================================================
INFO:scripts.fix_ebay_prices:✅ Price remediation completed: 68/68 listings updated
INFO:scripts.fix_ebay_prices:Next steps:
INFO:scripts.fix_ebay_prices:1. Wait for next sync cycle (30 seconds)
INFO:scripts.fix_ebay_prices:2. Verify listings transition from 'blocked' to 'pushable'
INFO:scripts.fix_ebay_prices:3. Check push status in dashboard or logs
```

### Step 4: Verify Success

Wait for the next sync cycle (30 seconds), then verify:

1. **Check Dashboard**: Go to `/warehouse` or `/inventory` and verify no "price below minimum" errors
2. **Check Sync Logs**: Go to `/stores` and check recent sync logs for the store
3. **Verify Push Status**: Check that listings transition from `push_state='blocked'` to `push_state='active'`

## CSV Report Format

The generated CSV contains the following columns:

| Column | Description | Example |
|--------|-------------|---------|
| `itemId` | eBay ItemID (numeric) | 123456789 |
| `sku` | Internal warehouse SKU | BEAT-001 |
| `store` | Store name | beatsoutlet |
| `oldPrice` | Original price (GBP) | 0.00 |
| `newPrice` | Updated price (GBP) | 0.99 |
| `changedAtUTC` | Timestamp of change (UTC) | 2025-01-31T14:30:22Z |
| `status` | Result status | success, error, dry-run |
| `errorMessage` | Error details (if failed) | eBay API error 21916841: ... |

## Error Handling

### Common Errors and Solutions

#### Error: "No API credentials configured"

**Cause**: Store has no `api_key` field or it's empty  
**Solution**: 
1. Go to `/ebay-setup`
2. Re-enter eBay API credentials
3. Test connection
4. Re-run remediation script

#### Error: "Missing access token"

**Cause**: OAuth token expired or not present  
**Solution**:
1. Re-authenticate via `/ebay-oauth` (if OAuth flow implemented)
2. Or manually update `user_token` in store's `api_key` JSON
3. Re-run remediation script

#### Error: "eBay API error 21916841: This listing may be removed"

**Cause**: Listing ended or removed from eBay  
**Solution**:
1. Mark listing as inactive in database
2. Re-import from eBay to sync current active listings
3. Re-run remediation on active listings only

#### Error: "Price 0.99 is below eBay minimum (£0.99)"

**Cause**: Rounding issue or incorrect minimum specified  
**Solution**:
1. Increase minimum to £1.00 with `--min 1.00`
2. Re-run script

### Partial Failures

If some listings fail during `--apply`:

1. **Check CSV Report**: Review `errorMessage` column for failed items
2. **Fix Individual Issues**: Address eBay API errors manually
3. **Re-run Script**: Re-run with `--apply` to fix remaining items (already-fixed items will skip)

## Rate Limiting

The script includes automatic rate limiting:

- **Delay Between Calls**: 0.5 seconds between each API call
- **Batch Size**: Default 20 items per batch (configurable with `--batch-size`)
- **Exponential Backoff**: Automatic retry on transient failures (built into eBay service)

If you encounter eBay rate limit errors:

1. Reduce batch size: `--batch-size 10`
2. Wait 5 minutes between script runs
3. Contact eBay support to increase your API limits

## Rollback

If prices were updated incorrectly:

### Option 1: Restore from Database Backup

```bash
# Restore database backup from before remediation
pg_restore -d inventory_db backup_before_remediation.dump
```

### Option 2: Manual Revert via eBay

1. Go to eBay Seller Hub
2. Bulk edit listings
3. Restore original prices from CSV `oldPrice` column

### Option 3: Re-run Script with Original Prices

1. Create a custom CSV with original prices
2. Modify `fix_ebay_prices.py` to read from CSV
3. Apply original prices back to eBay

## Monitoring

### During Remediation

Monitor the script output for:

- ✅ Success messages: `✅ Successfully updated`
- ❌ Error messages: `❌ Failed to update`
- Batch progress: `Processing batch X/Y`

### After Remediation

Monitor the following:

1. **Sync Logs**: Check `/stores` for recent sync activity
2. **Push Status**: Verify `push_state='active'` for updated listings
3. **Error Logs**: Check application logs for push failures
4. **eBay Seller Hub**: Verify prices updated correctly on eBay

## Safety Guidelines

1. **Always start with --dry-run**: Never skip the dry run step
2. **Review CSV before applying**: Check dry-run CSV for unexpected changes
3. **Backup database**: Create database backup before running `--apply`
4. **Test on single store first**: Use `--store` filter for initial testing
5. **Monitor during execution**: Watch script output for errors
6. **Verify results**: Check dashboard and eBay Seller Hub after completion

## Support

If you encounter issues not covered in this runbook:

1. **Check Logs**: Review application logs in `/tmp/logs/`
2. **Check CSV Report**: Review error messages in CSV
3. **Re-import from eBay**: Run full sync to refresh listing data
4. **Contact Support**: Provide CSV report and error logs

## Related Documentation

- [eBay Trading API - ReviseFixedPriceItem](https://developer.ebay.com/DevZone/XML/docs/Reference/eBay/ReviseFixedPriceItem.html)
- [eBay Minimum Pricing Policy](https://www.ebay.co.uk/help/selling/listings/creating-managing-listings/setting-price-item?id=4181)
- [System Architecture](./replit.md)
