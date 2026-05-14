# How to Adjust Warehouse Stock & Auto-Push to Marketplaces

## ✅ Step-by-Step Guide

### Step 1: Navigate to Warehouse Detail Page

**From the Inventory page** (the list you showed me):

1. Click on **any SKU** in the table - for example, click on "EB-CG-GOF"
2. This opens the **Warehouse Detail** page for that product

### Step 2: Click "Adjust Stock" Button

At the top of the Warehouse Detail page, you'll see:

```
┌─────────────────────────────────────────────┐
│  SKU: EB-CG-GOF                             │
│  ┌──────────────┐  ┌──────────────┐        │
│  │ Adjust Stock │  │ Back to List │        │
│  └──────────────┘  └──────────────┘        │
└─────────────────────────────────────────────┘
```

**Click the yellow "Adjust Stock" button** (it has a pencil icon)

### Step 3: Use the Stock Adjustment Modal

A popup window will open with these options:

```
┌─────────────────────────────────────────┐
│  Adjust Stock: EB-CG-GOF           ✕    │
├─────────────────────────────────────────┤
│                                         │
│  Current Available Quantity: 14         │
│                                         │
│  Adjustment Type:                       │
│  ┌─────────────────────────────────┐   │
│  │ ▼ Select adjustment type        │   │
│  └─────────────────────────────────┘   │
│  Options:                               │
│  - Stock In (receive new stock)         │
│  - Stock Out (sold/damaged)             │
│  - Set Quantity (override to exact)     │
│  - Manual Adjustment (corrections)      │
│                                         │
│  Quantity Change:                       │
│  ┌─────────────────────────────────┐   │
│  │ [Enter number]                  │   │
│  └─────────────────────────────────┘   │
│                                         │
│  Reason/Notes:                          │
│  ┌─────────────────────────────────┐   │
│  │ [Optional description]          │   │
│  └─────────────────────────────────┘   │
│                                         │
│  ┌──────────┐  ┌──────────┐           │
│  │  Submit  │  │  Cancel  │           │
│  └──────────┘  └──────────┘           │
└─────────────────────────────────────────┘
```

### Step 4: Fill Out the Form

**Example: Increase stock from 14 to 20**

1. **Adjustment Type**: Select "Stock In" (or "Set Quantity")
2. **Quantity Change**: 
   - If "Stock In": Enter `6` (14 + 6 = 20)
   - If "Set Quantity": Enter `20` (direct override)
3. **Reason**: Type "Received new shipment" (optional)
4. Click **Submit**

### Step 5: Watch the Automatic Push Happen

After you click Submit, you'll see a green success message:

```
✓ Stock adjusted for EB-CG-GOF. New quantity: 20.
  High-priority push queued for 1 marketplace(s).
```

**What happens behind the scenes:**

1. ✅ Warehouse stock updated to 20 units
2. ✅ High-priority push job created (Priority 10)
3. ✅ Background worker picks up the job
4. ✅ eBay listing updated to 20 units (takes 5-10 seconds)
5. ✅ Job marked as "success"

### Step 6: Verify the Push Worked

**On the Warehouse Detail page, scroll down to:**

1. **Marketplace Listings** section - shows all your eBay/Amazon listings
2. **Stock Movement History** section - shows the adjustment you just made
3. **Sync History** section - shows the push job that ran

**Or check eBay directly:**
- Go to eBay.com → My eBay → Selling
- Find listing for "The Game Of Life Goals"
- Verify quantity shows 20 units available

---

## 🔍 Quick Verification Test

**Test it right now with EB-CG-GOF:**

1. Go to **Inventory** page
2. Click on **"The Game Of Life Goals"** (SKU: EB-CG-GOF)
3. Click **"Adjust Stock"** button
4. Select **"Set Quantity"**
5. Enter **`20`**
6. Click **Submit**
7. Wait 10 seconds
8. Check eBay listing - should show 20 available

---

## ⚠️ Important Settings

**Your eBay store "beatsoutlet" has:**
- ✅ Auto Push Enabled: **TRUE** (good!)
- ✅ Push on Quantity Change: **TRUE** (good!)

**This means automatic push WILL work!**

If you had these set to FALSE, you'd see this message instead:
```
✓ Stock adjusted for EB-CG-GOF. New quantity: 20.
  No marketplaces have auto-push enabled.
```

---

## 📍 Where You Were vs. Where You Need to Be

### ❌ Where you were (won't trigger push):
**Inventory List Page** → Shows overview table, no adjustment controls

### ✅ Where you need to be (triggers push):
**Warehouse Detail Page** → Click on a SKU → Shows "Adjust Stock" button → Opens modal → Fill form → Submit → **Auto-push happens!**

---

## 🎯 The Full Flow

```
Inventory Page
    ↓
Click on SKU "EB-CG-GOF"
    ↓
Warehouse Detail Page Opens
    ↓
Click "Adjust Stock" Button (yellow)
    ↓
Modal Popup Opens
    ↓
Select Adjustment Type
    ↓
Enter Quantity
    ↓
Click Submit
    ↓
✅ Warehouse Updated
    ↓
✅ High-Priority Push Job Created
    ↓
✅ Worker Processes Job (5-10 seconds)
    ↓
✅ eBay Listing Updated
    ↓
DONE! Check eBay to verify.
```

---

## 🚀 Ready to Test?

Try it now with any product! The system is working perfectly - I just tested it and confirmed:
- ✅ Push job created successfully
- ✅ Job processed with no errors
- ✅ Status: SUCCESS

Just follow the steps above and you'll see it work!
