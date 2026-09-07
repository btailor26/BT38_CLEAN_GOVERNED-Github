"""Bind existing eBay shipment readback to the governed 8-hour recovery call.

Marketplace-dispatched orders and BT38-dispatched orders must converge on the
same MarketplaceOrder shipment truth. The existing exact eBay missing-tracking
readback is attached to the existing governed marketplace recovery function;
this adds no scheduler, poller, worker, shipment row or marketplace write path.
"""
from __future__ import annotations

from functools import wraps


def install_governed_ebay_runtime_recovery_alignment() -> None:
    from extensions import db
    from models import Store
    from services import governed_runtime_engine as runtime
    from services.governed_ebay_post_deploy_alignment import (
        _recover_recent_missing_tracking,
    )

    original = runtime.run_governed_marketplace_import_refresh
    if getattr(original, "_bt38_ebay_tracking_recovery_aligned", False):
        return

    @wraps(original)
    def aligned_marketplace_import_refresh(*args, **kwargs):
        result = original(*args, **kwargs)
        source = str(kwargs.get("source") or "").strip()
        if source != "full_sync_8h_recovery":
            return result

        recoveries = []
        stores = (
            Store.query
            .filter(Store.platform.ilike("%ebay%"))
            .filter(Store.is_active == True)  # noqa: E712
            .filter(Store.store_mode == "live")
            .order_by(Store.id.asc())
            .all()
        )
        for store in stores:
            try:
                recovery = _recover_recent_missing_tracking(
                    store,
                    max_days=30,
                )
            except Exception as exc:
                db.session.rollback()
                recovery = {
                    "success": False,
                    "bounded": True,
                    "reason": "ebay_missing_tracking_recovery_exception",
                    "error": str(exc),
                    "marketplace_write_started": False,
                    "polling_started": False,
                    "scheduler_started": False,
                }
            recoveries.append({
                "store_id": int(store.id),
                "store": str(store.name or ""),
                "recovery": recovery,
            })

        if isinstance(result, dict):
            result["ebay_tracking_recovery"] = recoveries
        runtime._last_ebay_tracking_recovery = {
            "at": runtime.datetime.utcnow(),
            "recoveries": recoveries,
        }
        return result

    aligned_marketplace_import_refresh._bt38_ebay_tracking_recovery_aligned = True
    runtime.run_governed_marketplace_import_refresh = aligned_marketplace_import_refresh


install_governed_ebay_runtime_recovery_alignment()
