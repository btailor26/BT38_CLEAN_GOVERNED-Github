# Align Marketplace Event Processing To One Governed Model

## Audit Findings

The architecture is not aligned with the approved BT38 execution model.

Evidence from audit:

- Amazon sales exist in MarketplaceOrder.
- warehouse_stock_id is linked.
- Group updates are not consistently occurring.
- Webhook path exists.
- 15-minute path exists.
- 8-hour path exists.
- Responsibilities are blurred between execution paths.
- 15-minute reconcile was temporarily narrowed to eBay-only.
- Full sync still contains mixed execution responsibilities.

## Approved BT38 Architecture

### Webhook Path

Purpose:

Immediate marketplace event processing.

Applies to:

- Amazon
- eBay
- Shopify
- TikTok
- Etsy
- Future marketplaces

Flow:

Marketplace Event
↓
Webhook Intake
↓
MarketplaceOrder / MarketplaceListing
↓
Warehouse
↓
Group
↓
Governed Correction

Must process:

- Sales
- Returns
- Cancellations
- Tracking updates
- Delivery updates
- Payment events
- FBA Pending
- FBA Received
- FBA Adjustments
- FBA Lost
- FBA Damaged
- FBA Reimbursements
- Listing events

Webhook is not controlled by 15-minute sync.

Webhook is not controlled by 8-hour sync.

Webhook performs its own job immediately.

---

### 15-Minute Light Reconcile

Purpose:

Verification and recovery only.

Flow:

All Enabled Marketplaces
↓
Verify missed events
↓
Verify missed orders
↓
Verify warehouse mutations
↓
Verify group alignment

Must support all marketplaces.

Must not be Amazon-only.

Must not be eBay-only.

Must not perform full imports.

Must not perform hydration work.

Controlled by fuse box.

---

### 8-Hour Full Sync

Purpose:

Reconciliation and hydration.

Flow:

Marketplace Import
↓
Inventory Hydration
↓
Listing Hydration
↓
Variation Hydration
↓
Marketplace Reconciliation

Must not be responsible for immediate order handling.

Controlled by fuse box.

---

## Alignment Rules

- Warehouse remains authority.
- Group follows warehouse.
- One governed execution model.
- No duplicate execution responsibilities.
- No marketplace-specific shortcuts.
- No UI changes.
- No adapter rewrites.
- No business rule changes.
- Wiring and authority alignment only.

## Required Audit Before Change

Identify exact blocks currently responsible for:

- Webhook processing
- 15-minute reconcile
- 8-hour sync

Then replace only those blocks.

No patch stacking.

No partial fixes.

Block replacement only.

