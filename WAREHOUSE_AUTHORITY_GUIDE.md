# Warehouse Authority System - User Guide

## ✅ Status: WAREHOUSE IS NOW AUTHORITATIVE

The warehouse is now the **single source of truth** for inventory. When you adjust stock in the warehouse, it automatically pushes to marketplaces.

---

## 🔧 How It Works

### When You Update Warehouse Stock:

1. **You adjust stock** via the warehouse detail page (e.g., set SKU quantity to 50)
2. **System saves** the new quantity to the database
3. **System finds marketplaces** with listings for that SKU
4. **System checks eligibility**: Only pushes to stores that have:
   - ✅ Active status (`is_active = True`)
   - ✅ Auto-push enabled (`auto_push_enabled = True`)
   - ✅ Push on quantity change (`push_on_quantity_change = True`)
5. **System enqueues HIGH-PRIORITY push jobs** to the queue
6. **Background workers process** the push jobs and update eBay/Amazon listings

You'll see a message like:
> "Stock adjusted for SKU123. New quantity: 50. High-priority push queued for 2 marketplace(s)."

---

## ⚙️ Requirements for Auto-Push to Work

### For eBay Stores:
Your eBay store **MUST** have these settings enabled:

1. Go to **Stores** page
2. Click **Edit** on your eBay store
3. Check these boxes:
   - ☑️ **Auto Push Enabled**
   - ☑️ **Push on Quantity Change**
4. Click **Save**

### For Amazon Stores:
Same requirements - check the store settings and enable:
- ☑️ **Auto Push Enabled**
- ☑️ **Push on Quantity Change**

**⚠️ If these are NOT enabled, warehouse updates will NOT push to marketplaces.**

---

## 🚨 Known Limitations

### Queue Starvation (High-Priority Jobs Can Be Blocked)

**The Problem:**
- The system uses a **sequential job queue** (one worker per store)
- If a long-running sync job is processing (e.g., importing 1000 eBay listings)
- Your high-priority push job **waits behind it** in the queue
- This can delay warehouse updates from reaching marketplaces

**Why It Happens:**
- Each store has one worker thread
- Workers process jobs one at a time, in priority order
- A 5-minute import job blocks all push jobs until it finishes

**The Fix (Future Enhancement):**
We need to implement a **dedicated high-priority worker lane** that:
- Bypasses the regular queue for urgent push jobs
- Guarantees warehouse updates push immediately
- Prevents starvation by long-running sync jobs

**Current Workaround:**
- Use the **Manual Push** button on warehouse detail page
- This enqueues a high-priority job that processes as soon as current job finishes
- Monitor the **Stores** page to see if jobs are stuck (spinning icon)

---

## 📋 How to Verify It's Working

### Test End-to-End:

1. **Pick a product** with eBay/Amazon listings
2. **Go to warehouse detail page** for that SKU
3. **Adjust stock** (e.g., change quantity from 10 to 50)
4. **Check the flash message**:
   - ✅ "High-priority push queued for X marketplace(s)" = Working!
   - ⚠️ "No marketplaces have auto-push enabled" = Check store settings
5. **Wait 1-2 minutes** for workers to process
6. **Check eBay listing** directly on eBay.com - quantity should update to 50
7. **Check sync logs** on warehouse detail page - look for recent "Push" logs

### If Not Working:

#### Message: "No marketplaces have auto-push enabled"
**Solution:** Enable auto-push flags in store settings (see Requirements section above)

#### Message: "Push enqueue failed"
**Solution:** Check application logs for errors - there may be a database connection issue

#### Push job stuck for >5 minutes:
**Solution:** Long-running sync job is blocking the queue. Wait for it to finish, or restart the application to reset stuck jobs.

---

## 🔄 Manual Push (Backup Method)

If automatic push isn't working, you can always push manually:

1. Go to **Warehouse Detail** page for the SKU
2. Click **Push to All Marketplaces** button at the bottom
3. This enqueues a high-priority push job
4. Wait 1-2 minutes for processing
5. Verify on marketplace website

---

## 🏗️ Technical Architecture

### What Changed:

**BEFORE (Broken):**
- Warehouse adjust → Background thread push → No priority → Often failed silently
- No queue visibility
- No retry mechanism

**AFTER (Fixed):**
- Warehouse adjust → High-priority queue job → Reliable processing
- Jobs visible in queue with priority
- Auto-retry on failure
- Proper store eligibility checks

### Code Changes:
- **File:** `routes.py` (lines 2702-2745)
- **Method:** `warehouse_adjust` route
- **Change:** Replaced `trigger_automatic_push()` background thread with `enqueue_sync_job()` queue system

---

## 📊 Monitoring & Troubleshooting

### Check Store Status:
Go to **Stores** page and look for:
- ✅ Green checkmark = Store syncing normally
- 🔄 Spinning icon = Jobs processing
- ❌ Red X = Error status (check sync logs)

### Check Sync Logs:
Go to **Warehouse Detail** page and scroll to sync logs table:
- Look for recent "Push" operations
- Check "Result" column for success/error
- Read error messages for clues

### Check Job Queue:
Currently there's no UI to view the queue (future enhancement), but you can:
- Check application logs for "Enqueuing job" messages
- Monitor store status icons for activity
- Look at sync logs to see when jobs completed

---

## 🎯 Summary: What You Need to Know

1. ✅ **Warehouse IS authoritative** - stock changes push to marketplaces automatically
2. ⚙️ **Enable auto-push flags** on your stores for it to work
3. ⚠️ **High-priority jobs can be delayed** by long-running syncs (queue starvation)
4. 🔄 **Manual push button** is always available as backup
5. 📊 **Monitor sync logs** to verify pushes are working

---

## 📞 Need Help?

If warehouse updates still aren't pushing to marketplaces:
1. Check store settings (auto-push enabled)
2. Check sync logs for error messages
3. Try manual push button
4. Check if long-running sync job is blocking the queue
5. Restart the application to reset stuck jobs
