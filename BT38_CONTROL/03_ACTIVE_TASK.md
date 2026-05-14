# BT38 ACTIVE TASK

## Current objective
Fix marketplace connection state, starting with eBay.

## Current stable baseline
- Compact warehouse layout is deployed on Fly.
- Active route system is app.py -> routes.py -> routes_bp.
- routes_clean.py is legacy and isolated.
- Active architecture is documented in BT38_CONTROL/07_ACTIVE_ARCHITECTURE.md.

## Exact failure to prove
eBay connection state is not reliably updating after OAuth/connection flow.
Known symptoms:
- eBay connection can appear successful but store remains inactive or invalid.
- Store page may show mixed connection messages.
- OAuth/token/save/active-state flow may be mismatched.

## Restrictions
- Do not touch warehouse layout.
- Do not touch sidebar/nav/logo.
- Do not restore old routes.
- Do not edit routes_clean.py.
- Do not deploy until patch is proven and approved.
- One path only: active routes.py.

## Success condition
eBay connection flow must clearly prove:
1. correct button/route is used,
2. OAuth start route exists,
3. callback route exists,
4. token exchange uses correct credentials,
5. token is saved to the right store,
6. store active/connected state updates only after valid connection,
7. user returns to Stores page with correct status.

## Next step
Audit active eBay connection code in routes.py, ebay_service.py, stores.html, edit_store.html, and ebay_oauth.html.
