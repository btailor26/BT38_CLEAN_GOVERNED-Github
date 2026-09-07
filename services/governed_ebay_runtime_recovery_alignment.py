"""Bind existing eBay shipment readback to the governed 8-hour recovery cycle.

Marketplace-dispatched orders and BT38-dispatched orders must converge on the
same MarketplaceOrder shipment truth. The exact eBay missing-tracking readback
already owns the marketplace side of that contract. This module binds that
existing readback directly to the existing full-recovery cycle; it creates no
second order path, poller, worker, marketplace write or shipment proxy.
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

    original_cycle = runtime._run_full_sync_cycle
    if getattr(original_cycle, "_bt38_ebay_tracking_recovery_aligned", False):
        return

    @wraps(original_cycle)
    def aligned_full_sync_cycle():
        # Preserve the existing marketplace hydration first. eBay shipment
        # readback is recovery enrichment of existing MarketplaceOrder rows,
        # never a replacement importer or shipment writer.
        original_cycle()

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

        # Keep runtime status observable without creating a second scheduler.
        runtime._last_ebay_tracking_recovery = {
            "at": runtime.datetime.utcnow(),
            "recoveries": recoveries,
        }

    aligned_full_sync_cycle._bt38_ebay_tracking_recovery_aligned = True
    runtime._run_full_sync_cycle = aligned_full_sync_cycle


install_governed_ebay_runtime_recovery_alignment()
