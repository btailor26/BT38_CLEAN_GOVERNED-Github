"""BT38 governed warehouse sync safe probe.

This manual sync endpoint must not bulk-push all listings or import route helpers.
It checks the governed fuse path and returns JSON quickly.
"""

from datetime import datetime

from app import db
from models import MarketplaceListing, Store, SystemLog
from services.runtime_action_guard import is_runtime_action_allowed


def run_governed_warehouse_sync(store_id=None, actor="manual-warehouse-sync", limit=5):
    store = None
    if store_id:
        store = db.session.get(Store, int(store_id))

    sync_guard = is_runtime_action_allowed(
        store=store,
        action_type="sync",
        manual=True,
        context={"source": "governed_warehouse_sync_probe", "store_id": store_id},
    )

    if not sync_guard.get("allowed"):
        return {
            "success": False,
            "ok": False,
            "governed": True,
            "execution_blocked": True,
            "fuse_box_checked": True,
            "reason": sync_guard.get("reason"),
            "mode": "safe_probe",
            "store_id": store_id,
        }

    query = db.session.query(MarketplaceListing).filter(
        MarketplaceListing.is_active == True,  # noqa: E712
        MarketplaceListing.warehouse_stock_id.isnot(None),
    )

    if store_id:
        query = query.filter(MarketplaceListing.store_id == int(store_id))

    listings = query.order_by(MarketplaceListing.id).limit(max(1, int(limit or 5))).all()

    results = []
    for listing in listings:
        push_guard = is_runtime_action_allowed(
            store=listing.store,
            action_type="push",
            manual=True,
            context={"source": "governed_warehouse_sync_probe_listing", "listing_id": listing.id},
        )

        results.append({
            "listing_id": listing.id,
            "sku": listing.external_sku,
            "store_id": listing.store_id,
            "platform": getattr(listing.store, "platform", None),
            "ok": bool(push_guard.get("allowed")),
            "execution_blocked": not bool(push_guard.get("allowed")),
            "reason": push_guard.get("reason") or "Listing eligible by fuse board.",
        })

    try:
        db.session.add(SystemLog(
            log_type="governed_warehouse_sync_probe",
            message=f"governed_warehouse_sync probe checked={len(results)}",
            details=f"store_id={store_id} actor={actor} limit={limit}"[:1000],
            created_at=datetime.utcnow(),
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()

    return {
        "success": True,
        "ok": True,
        "governed": True,
        "manual": True,
        "mode": "safe_probe",
        "store_id": store_id,
        "total": len(results),
        "checked": len(results),
        "pushed": 0,
        "blocked": sum(1 for row in results if row.get("execution_blocked")),
        "message": "Warehouse sync safe probe completed. No marketplace bulk push executed.",
        "results": results,
    }
