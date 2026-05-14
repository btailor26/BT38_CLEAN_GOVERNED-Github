# BT38 SYSTEM BLUEPRINT

## Main areas
1. Landing / sign-in flow
2. Profile setup
3. Upload / P&L reporting
4. Store connections
5. Marketplace OAuth
6. Warehouse / inventory truth page
7. Sync jobs and workers
8. Reports / downloads
9. Admin/system activity

## Inventory source-of-truth model
- /inventory is the warehouse truth page.
- Warehouse stock controls editable marketplace stock.
- Amazon FBA/AFN is read-only.
- Amazon FBM/MFN is editable/pushable.
- eBay/TikTok/manual marketplaces should connect into the same warehouse truth model.
- Group Source controls group-level behaviour.
- MCF is fulfilment routing from Amazon FBA stock only.

## Marketplace connection model
- Store page should show clear connection state.
- OAuth routes must redirect correctly.
- Callback must save tokens correctly.
- Store active state must update only when connection is genuinely valid.
- Failed connection must not show as successful.

## Sync model
- Manual bulk sync requires selected rows.
- Single listing sync can be triggered by row marketplace icon.
- Passive changes should wait for controlled scheduled sync.
- Workers/schedulers must not run unnecessary syncs before the setup is proven.
- Webhooks/notifications are planned to reduce polling.

## Upload/P&L model
- Upload page accepts marketplace/accounting/bank files.
- System checks files before analysis.
- Unclear mappings must trigger questions, not guesses.
- Run Summary uses temporary checked state.
- Download report uses one credit.
- Report should include company/profile details where available.

## UI rule
Approved layouts must be preserved unless a new visual direction is approved first.
