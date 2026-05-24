"""BT38 governed warehouse sync execution.

Rules:
- Fuse box remains the authority.
- UI buttons are shortcuts only.
- No legacy queue workers are revived.
- No old push_stock routes are used.
- All-store warehouse sync must discover stores first, then pass each store into
  the fuse box. It must never ask the fuse box to approve sync with store=None.
"""

from __future__ import annotations

from datetime import datetime

from app import db
from models import MarketplaceListing, Store, SystemLog
from services.runtime_action_guard import is_runtime_action_allowed


def _log_sync(message: str, details: str = "") -> None:
    try:
        db.session.add(SystemLog(
            log_type="governed_warehouse_sync",
            message=message,
            details=(details or "")[:1000],
            created_at=datetime.utcnow(),
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()


def _live_candidate_stores():
    """Return stores that are switched on and structurally eligible for sync checks."""
    return (
        db.session.query(Store)
        .filter(Store.is_active == True)  # noqa: E712
        .order_by(Store.id)
        .all()
    )


def _combine_store_results(store_results, actor):
    pushed = sum(int(row.get("pushed") or 0) for row in store_results)
    blocked = sum(int(row.get("blocked") or 0) for row in store_results)
    failed = sum(int(row.get("failed") or 0) for row in store_results)
    checked = sum(int(row.get("checked") or 0) for row in store_results)
    total = sum(int(row.get("total") or 0) for row in store_results)

    blocked_stores = [row for row in store_results if row.get("execution_blocked")]
    failed_stores = [row for row in store_results if row.get("ok") is False and not row.get("execution_blocked")]

    _log_sync(
        "Governed all-store warehouse sync executed",
        (
            f"actor={actor} stores={len(store_results)} total={total} checked={checked} "
            f"pushed={pushed} blocked={blocked} failed={failed} "
            f"blocked_stores={len(blocked_stores)} failed_stores={len(failed_stores)}"
        ),
    )

    return {
        "success": failed == 0,
        "ok": failed == 0,
        "governed": True,
        "manual": True,
        "mode": "governed_all_store_execution",
        "store_scope": "all_active_stores",
        "stores_checked": len(store_results),
        "total": total,
        "checked": checked,
        "pushed": pushed,
        "blocked": blocked,
        "failed": failed,
        "message": (
            f"Governed warehouse sync executed across {len(store_results)} active store(s). "
            f"Pushed: {pushed}. Blocked: {blocked}. Failed: {failed}."
        ),
        "results": store_results,
    }


def run_governed_warehouse_sync(store_id=None, actor="manual-warehouse-sync", limit=None):
    if not store_id:
        stores = _live_candidate_stores()

        if not stores:
            _log_sync(
                "Governed all-store warehouse sync found no active stores",
                f"actor={actor}",
            )
            return {
                "success": True,
                "ok": True,
                "governed": True,
                "manual": True,
                "mode": "governed_all_store_execution",
                "store_scope": "all_active_stores",
                "stores_checked": 0,
                "total": 0,
                "checked": 0,
                "pushed": 0,
                "blocked": 0,
                "failed": 0,
                "message": "No active stores found for governed warehouse sync.",
                "results": [],
            }

        store_results = []
        for store in stores:
            result = run_governed_warehouse_sync(
                store_id=store.id,
                actor=actor,
                limit=limit,
            )
            if isinstance(result, dict):
                result.setdefault("store_id", store.id)
                result.setdefault("store_name", getattr(store, "name", None))
                result.setdefault("platform", getattr(store, "platform", None))
                store_results.append(result)
            else:
                store_results.append({
                    "success": False,
                    "ok": False,
                    "store_id": store.id,
                    "store_name": getattr(store, "name", None),
                    "platform": getattr(store, "platform", None),
                    "failed": 1,
                    "error": str(result),
                })

        return _combine_store_results(store_results, actor)

    store = db.session.get(Store, int(store_id))
    if not store:
        return {
            "success": False,
            "ok": False,
            "governed": True,
            "execution_blocked": True,
            "fuse_box_checked": True,
            "reason": f"Store {store_id} not found.",
            "mode": "governed_execution",
            "store_id": store_id,
        }

    sync_guard = is_runtime_action_allowed(
        store=store,
        action_type="sync",
        manual=True,
        context={
            "source": "governed_warehouse_sync_execution",
            "store_id": store_id,
            "actor": actor,
            "authority": "SystemConfig fuse box",
        },
    )

    if not sync_guard.get("allowed"):
        _log_sync(
            "Governed warehouse sync blocked by fuse box",
            f"store_id={store_id} actor={actor} reason={sync_guard.get('reason')}",
        )
        return {
            "success": False,
            "ok": False,
            "governed": True,
            "execution_blocked": True,
            "fuse_box_checked": True,
            "reason": sync_guard.get("reason"),
            "mode": "governed_execution",
            "store_id": store_id,
            "store_name": getattr(store, "name", None),
            "platform": getattr(store, "platform", None),
            "guard": sync_guard,
            "total": 0,
            "checked": 0,
            "pushed": 0,
            "blocked": 0,
            "failed": 0,
        }

    query = db.session.query(MarketplaceListing).filter(
        MarketplaceListing.is_active == True,  # noqa: E712
        MarketplaceListing.warehouse_stock_id.isnot(None),
        MarketplaceListing.store_id == int(store_id),
    )

    query = query.order_by(MarketplaceListing.id)

    if limit:
        query = query.limit(max(1, int(limit)))

    listings = query.all()

    if not listings:
        _log_sync(
            "Governed warehouse sync found no pushable listings",
            f"store_id={store_id} actor={actor}",
        )
        return {
            "success": True,
            "ok": True,
            "governed": True,
            "manual": True,
            "mode": "governed_execution",
            "store_id": store_id,
            "store_name": getattr(store, "name", None),
            "platform": getattr(store, "platform", None),
            "total": 0,
            "checked": 0,
            "pushed": 0,
            "blocked": 0,
            "failed": 0,
            "message": "No active linked marketplace listings found for governed sync.",
            "results": [],
            "guard": sync_guard,
        }

    from governed_routes import _push_one_listing

    results = []

    for listing in listings:
        push_guard = is_runtime_action_allowed(
            store=listing.store,
            action_type="push",
            manual=True,
            context={
                "source": "governed_warehouse_sync_listing",
                "listing_id": listing.id,
                "actor": actor,
                "authority": "SystemConfig fuse box",
            },
        )

        if not push_guard.get("allowed"):
            results.append({
                "listing_id": listing.id,
                "sku": listing.external_sku,
                "store_id": listing.store_id,
                "platform": getattr(listing.store, "platform", None),
                "ok": False,
                "success": False,
                "execution_blocked": True,
                "fuse_box_checked": True,
                "reason": push_guard.get("reason"),
            })
            continue

        try:
            result = _push_one_listing(
                listing_id=listing.id,
                quantity=None,
                actor=actor,
                source="governed_warehouse_sync",
            )
            if isinstance(result, dict):
                result.setdefault("listing_id", listing.id)
                result.setdefault("sku", listing.external_sku)
                result.setdefault("store_id", listing.store_id)
                result.setdefault("platform", getattr(listing.store, "platform", None))
                result.setdefault("fuse_box_checked", True)
                results.append(result)
            else:
                results.append({
                    "listing_id": listing.id,
                    "sku": listing.external_sku,
                    "store_id": listing.store_id,
                    "platform": getattr(listing.store, "platform", None),
                    "ok": True,
                    "success": True,
                    "result": str(result),
                })
        except Exception as exc:
            results.append({
                "listing_id": listing.id,
                "sku": listing.external_sku,
                "store_id": listing.store_id,
                "platform": getattr(listing.store, "platform", None),
                "ok": False,
                "success": False,
                "error": str(exc),
            })

    pushed = sum(1 for row in results if row.get("ok") or row.get("success"))
    blocked = sum(1 for row in results if row.get("execution_blocked"))
    failed = len(results) - pushed - blocked

    _log_sync(
        "Governed warehouse sync executed",
        f"store_id={store_id} actor={actor} total={len(results)} pushed={pushed} blocked={blocked} failed={failed}",
    )

    return {
        "success": failed == 0,
        "ok": failed == 0,
        "governed": True,
        "manual": True,
        "mode": "governed_execution",
        "store_id": store_id,
        "store_name": getattr(store, "name", None),
        "platform": getattr(store, "platform", None),
        "total": len(results),
        "checked": len(results),
        "pushed": pushed,
        "blocked": blocked,
        "failed": failed,
        "message": f"Governed warehouse sync executed for store {store_id}. Pushed: {pushed}. Blocked: {blocked}. Failed: {failed}.",
        "results": results,
        "guard": sync_guard,
    }
