"""Align the existing 8-hour governed recovery with eBay shipment truth.

The exact eBay missing-tracking recovery already exists in
``governed_ebay_post_deploy_alignment``. This module only attaches that existing
bounded readback to the existing 8-hour runtime recovery cycle. It does not
create a second order path, poller, worker, marketplace write, shipment proxy,
or notification/auth mutation.
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
    def aligned_refresh(store_id=None, source="governed_runtime_engine"):
        result = original(store_id=store_id, source=source)

        # This alignment belongs only to the already-existing automatic 8-hour
        # recovery cycle. Manual/initial hydration retains its current contract.
        if source != "full_sync_8h_recovery":
            return result
        if not isinstance(result, dict) or result.get("success") is not True:
            return result
        if result.get("reason") == "import_fuses_blocked":
            return result

        query = (
            Store.query
            .filter(Store.platform.ilike("%ebay%"))
            .filter(Store.is_active == True)  # noqa: E712
            .filter(Store.store_mode == "live")
        )
        if store_id is not None:
            query = query.filter(Store.id == int(store_id))

        recoveries = []
        for store in query.order_by(Store.id.asc()).all():
            try:
                recovery = _recover_recent_missing_tracking(
                    store,
                    max_days=7,
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

            for row in result.get("results") or []:
                if int(row.get("store_id") or 0) != int(store.id):
                    continue
                row["tracking_recovery"] = recovery
                row["success"] = bool(row.get("success", True)) and bool(
                    recovery.get("success")
                )
                break

        result["ebay_tracking_recovery"] = recoveries
        result["ebay_tracking_recovery_started"] = bool(recoveries)
        result["marketplace_write_started"] = False
        return result

    aligned_refresh._bt38_ebay_tracking_recovery_aligned = True
    runtime.run_governed_marketplace_import_refresh = aligned_refresh


install_governed_ebay_runtime_recovery_alignment()
