# eBay API Limit Increase - Instructions

## Current Status
- **Auto-sync**: PAUSED (manually disabled)
- **Sync frequency**: Changed from 10min → 30min (reduces API usage by 66%)
- **Issue**: Error 518 - eBay API call limit exceeded
- **Active listings**: 217 items ready to push once quota is restored

## How to Request eBay API Limit Increase

### Contact eBay Developer Support

**Method 1: Developer Portal**
1. Log in: https://developer.ebay.com/
2. Click "Support" → "Contact Us"
3. Use the email template below

**Method 2: Developer Forums**
1. Visit: https://community.ebay.com/t5/Developer-APIs/bd-p/ebay-apis
2. Post your request with same details
3. Tag: "API Limits" and "Trading API"

### Email Template

```
Subject: Request for Increased API Call Limits - GetMyeBaySelling

Hello eBay Developer Support,

I am experiencing API quota limitations (Error 518) with my application 
and would like to request an increase in my daily API call limits.

Application Details:
- App ID: [Find this in your eBay developer account]
- API Name: Trading API (GetMyeBaySelling)
- Current Issue: Receiving Error 518 "Call usage limit exceeded"

Business Justification:
- Active Listings: 217 items
- Sync Frequency Needed: Every 30 minutes for inventory management
- Estimated Daily Calls: ~240 calls/day (reduced from 720)
- Use Case: Multi-channel inventory synchronization system

I have already reduced my sync frequency from 10 to 30 minutes to minimize 
API usage. I am requesting an increase to support my legitimate business 
operations.

Thank you for your assistance.

Best regards,
[Your Name/Business Name]
```

## What Happens Next

1. **eBay's Response Time**: Usually 2-5 business days
2. **Typical Quota Increase**: 5x-10x current limits
3. **Automatic Resume**: Your quota resets at midnight Pacific Time daily

## Re-Enable Auto-Sync (After Quota Increase)

Once eBay approves your request:

1. Go to your inventory management dashboard
2. Navigate to Stores → beatsoutlet
3. Click "Edit Store Settings"
4. Enable "Auto Push Enabled"
5. Or run this SQL query:

```sql
UPDATE stores 
SET auto_push_enabled = true,
    pause_reason = NULL
WHERE id = 1;
```

## Monitor Your Usage

After re-enabling, watch for:
- Sync logs should show "Imported X items" (not "1 import errors")
- No more Error 518 messages
- Successfully pushed items to eBay

## Need Help?

If you continue seeing Error 518 after:
- Waiting for midnight PST quota reset, OR
- Receiving eBay's approval

Then contact me for further troubleshooting.

---
Generated: November 11, 2025
