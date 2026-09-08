"""One-time governed recovery of missing marketplace dispatch truth.

This operator action is intentionally finite and DB-driven. It selects only
existing Amazon/eBay FBM orders that are already dispatched (or later) in BT38
and still lack carrier or tracking truth, then hands each exact marketplace
order back to the existing governed readback authority.

There is no date window, marketplace-wide order scan, worker, scheduler, queue,
or marketplace write. The historical boundary is the first dispatched row
already present in BT38 for each store and the candidate set runs through the
latest dispatched row currently in the DB.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from sqlalchemy import func, or_

from app import app
from extensions import db
from models import MarketplaceOrder, Store


_DISPATCHED_STATUSES = {
    "shipped",
    "partially_shipped",
    "partiallyshipped",
    "picked_up",
    "accepted",
    "carrier_accepted",
    "in_transit",
    "out_for_delivery",
    "delivered",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _platform(store: Store) -> str:
    value = _clean(getattr(store, "platform", "")).lower()
    if "amazon" in value:
        return "amazon"
    if "ebay" in value:
        return "ebay"
    return ""


def _first_dispatch_at(store_id: int):
    return (
        db.session.query(
            func.min(
                func.coalesce(
                    MarketplaceOrder.shipped_at,
                    MarketplaceOrder.updated_at,
                    MarketplaceOrder.created_at,
                )
            )
        )
        .filter(
            MarketplaceOrder.store_id == int(store_id),
            MarketplaceOrder.fulfillment_type == "FBM",
            func.lower(func.coalesce(MarketplaceOrder.status, "")).in_(
                sorted(_DISPATCHED_STATUSES)
            ),
        )
        .scalar()
    )


def _candidate_order_ids(store_id: int) -> list[str]:
    rows = (
        db.session.query(MarketplaceOrder.marketplace_order_id)
        .filter(
            MarketplaceOrder.store_id == int(store_id),
            MarketplaceOrder.fulfillment_type == "FBM",
            MarketplaceOrder.marketplace_order_id.isnot(None),
            func.lower(func.coalesce(MarketplaceOrder.status, "")).in_(
                sorted(_DISPATCHED_STATUSES)
            ),
            or_(
                MarketplaceOrder.tracking_number.is_(None),
                func.btrim(func.coalesce(MarketplaceOrder.tracking_number, "")) == "",
                MarketplaceOrder.carrier.is_(None),
                func.btrim(func.coalesce(MarketplaceOrder.carrier, "")) == "",
            ),
        )
        .distinct()
        .order_by(MarketplaceOrder.marketplace_order_id.asc())
        .all()
    )
    return [
        _clean(order_id)
        for (order_id,) in rows
        if _clean(order_id)
    ]


def _database_readback(store_id: int, order_id: str) -> dict[str, Any]:
    rows = (
        MarketplaceOrder.query
        .filter(
            MarketplaceOrder.store_id == int(store_id),
            MarketplaceOrder.marketplace_order_id == order_id,
        )
        .order_by(MarketplaceOrder.id.asc())
        .all()
    )
    return {
        "carrier": next((_clean(row.carrier) for row in rows if _clean(row.carrier)), None),
        "tracking_number": next(
            (_clean(row.tracking_number) for row in rows if _clean(row.tracking_number)),
            None,
        ),
        "statuses": sorted({_clean(row.status).lower() for row in rows if _clean(row.status)}),
        "shipped_at": next(
            (row.shipped_at.isoformat() for row in rows if row.shipped_at is not None),
            None,
        ),
    }


def _recover_amazon(store: Store, order_id: str) -> dict[str, Any]:
    from services.governed_amazon_shipping_label_readback import (
        hydrate_amazon_purchased_label_for_order,
    )
    from services.governed_amazon_tracking_readback import (
        hydrate_amazon_tracking_for_order,
    )

    tracking = hydrate_amazon_tracking_for_order(
        store=store,
        marketplace_order_id=order_id,
        source="operator_dispatch_history_recovery",
    )

    db.session.expire_all()
    readback = _database_readback(store.id, order_id)
    shipping_label: dict[str, Any] | None = None
    if not readback.get("tracking_number") or not readback.get("carrier"):
        shipping_label = hydrate_amazon_purchased_label_for_order(
            store=store,
            marketplace_order_id=order_id,
            source="operator_dispatch_history_recovery",
        )
        db.session.expire_all()
        readback = _database_readback(store.id, order_id)

    return {
        "success": bool(tracking.get("success")),
        "tracking_readback": tracking,
        "shipping_label_readback": shipping_label,
        "database_readback": readback,
        "marketplace_write_started": False,
    }


def _recover_ebay(store: Store, order_id: str) -> dict[str, Any]:
    from services.governed_exact_ebay_order_hydration import hydrate_exact_ebay_order

    hydration = hydrate_exact_ebay_order(
        store=store,
        marketplace_order_id=order_id,
        source="operator_dispatch_history_recovery",
    )
    db.session.expire_all()
    return {
        "success": bool(hydration.get("success")),
        "hydration": hydration,
        "database_readback": _database_readback(store.id, order_id),
        "marketplace_write_started": False,
    }


def recover_missing_dispatch_truth_from_db_start() -> dict[str, Any]:
    stores = (
        Store.query
        .filter(Store.is_active == True)  # noqa: E712
        .order_by(Store.id.asc())
        .all()
    )

    summary: dict[str, Any] = {
        "success": True,
        "operator_action": True,
        "automatic_startup_recovery": False,
        "polling_started": False,
        "scheduler_started": False,
        "worker_started": False,
        "marketplace_write_started": False,
        "stores": [],
    }
    totals = defaultdict(int)

    for store in stores:
        platform = _platform(store)
        if platform not in {"amazon", "ebay"}:
            continue

        first_dispatch_at = _first_dispatch_at(store.id)
        order_ids = _candidate_order_ids(store.id)
        store_result: dict[str, Any] = {
            "store_id": int(store.id),
            "store_name": _clean(getattr(store, "name", "")),
            "platform": platform,
            "first_dispatch_at": (
                first_dispatch_at.isoformat() if first_dispatch_at is not None else None
            ),
            "candidate_orders": len(order_ids),
            "resolved": 0,
            "still_missing": 0,
            "failed": 0,
            "orders": [],
        }

        for order_id in order_ids:
            totals["selected"] += 1
            try:
                if platform == "amazon":
                    result = _recover_amazon(store, order_id)
                else:
                    result = _recover_ebay(store, order_id)
            except Exception as exc:
                db.session.rollback()
                result = {
                    "success": False,
                    "reason": "exact_dispatch_recovery_exception",
                    "error": str(exc)[:1000],
                    "marketplace_write_started": False,
                }

            db.session.expire_all()
            readback = _database_readback(store.id, order_id)
            resolved = bool(readback.get("tracking_number") and readback.get("carrier"))
            if not result.get("success"):
                store_result["failed"] += 1
                totals["failed"] += 1
            elif resolved:
                store_result["resolved"] += 1
                totals["resolved"] += 1
            else:
                store_result["still_missing"] += 1
                totals["still_missing"] += 1

            store_result["orders"].append({
                "order_id": order_id,
                "success": bool(result.get("success")),
                "resolved": resolved,
                "database_readback": readback,
                "result": result,
            })

        summary["stores"].append(store_result)

    summary["selected"] = int(totals["selected"])
    summary["resolved"] = int(totals["resolved"])
    summary["still_missing"] = int(totals["still_missing"])
    summary["failed"] = int(totals["failed"])
    summary["success"] = summary["failed"] == 0
    return summary


if __name__ == "__main__":
    with app.app_context():
        print(json.dumps(recover_missing_dispatch_truth_from_db_start(), default=str))
