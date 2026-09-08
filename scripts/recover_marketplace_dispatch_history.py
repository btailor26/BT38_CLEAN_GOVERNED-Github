"""One-time governed recovery of missing marketplace dispatch truth.

This operator action is intentionally finite and DB-driven. Amazon and eBay
select only existing dispatched FBM orders whose persisted marketplace truth is
incomplete, then hand each exact order back to the already-governed exact read
paths. Amazon refreshes the existing order profile/promise and package tracking;
Amazon label-cost recovery is deliberately excluded from this pass. eBay keeps
its existing exact fulfillment, promise and confirmed SHIPPING_LABEL spend read.

There is no date window, marketplace-wide order scan, worker, scheduler, queue,
or marketplace write. The historical boundary is the first dispatched row
already present in BT38 for each store and the candidate set runs through the
latest dispatched row currently in the DB.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from sqlalchemy import func, text

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


def _candidate_order_ids(store_id: int, *, platform: str) -> list[str]:
    if platform == "ebay":
        rows = db.session.execute(
            text(
                """
                SELECT DISTINCT mo.marketplace_order_id
                FROM marketplace_orders mo
                LEFT JOIN fbm_order_operational_state fos
                  ON fos.store_id = mo.store_id
                 AND fos.marketplace_order_id = mo.marketplace_order_id
                WHERE mo.store_id = :store_id
                  AND UPPER(COALESCE(mo.fulfillment_type, '')) = 'FBM'
                  AND LOWER(COALESCE(mo.status, '')) = ANY(:statuses)
                  AND NULLIF(BTRIM(COALESCE(mo.marketplace_order_id, '')), '') IS NOT NULL
                  AND (
                    NULLIF(BTRIM(COALESCE(mo.tracking_number, '')), '') IS NULL
                    OR NULLIF(BTRIM(COALESCE(mo.carrier, '')), '') IS NULL
                    OR fos.ship_by_at IS NULL
                    OR (fos.earliest_delivery_at IS NULL AND fos.latest_delivery_at IS NULL)
                    OR NOT EXISTS (
                        SELECT 1
                        FROM shipping_spend_ledger ssl
                        WHERE ssl.store_id = mo.store_id
                          AND ssl.marketplace_order_id = mo.marketplace_order_id
                          AND ssl.confirmed = TRUE
                    )
                  )
                ORDER BY mo.marketplace_order_id ASC
                """
            ),
            {"store_id": int(store_id), "statuses": sorted(_DISPATCHED_STATUSES)},
        ).all()
        return [_clean(order_id) for (order_id,) in rows if _clean(order_id)]

    # Amazon uses the same existing exact-order profile + tracking authorities.
    # Select promise gaps too; otherwise an order with carrier/tracking already
    # present is skipped even when Seller Central's delivery promise was never
    # persisted. Amazon label price is intentionally not part of this pass.
    rows = db.session.execute(
        text(
            """
            SELECT DISTINCT mo.marketplace_order_id
            FROM marketplace_orders mo
            LEFT JOIN fbm_order_operational_state fos
              ON fos.store_id = mo.store_id
             AND fos.marketplace_order_id = mo.marketplace_order_id
            WHERE mo.store_id = :store_id
              AND UPPER(COALESCE(mo.fulfillment_type, '')) = 'FBM'
              AND LOWER(COALESCE(mo.status, '')) = ANY(:statuses)
              AND NULLIF(BTRIM(COALESCE(mo.marketplace_order_id, '')), '') IS NOT NULL
              AND (
                NULLIF(BTRIM(COALESCE(mo.tracking_number, '')), '') IS NULL
                OR NULLIF(BTRIM(COALESCE(mo.carrier, '')), '') IS NULL
                OR fos.ship_by_at IS NULL
                OR (fos.earliest_delivery_at IS NULL AND fos.latest_delivery_at IS NULL)
              )
            ORDER BY mo.marketplace_order_id ASC
            """
        ),
        {"store_id": int(store_id), "statuses": sorted(_DISPATCHED_STATUSES)},
    ).all()
    return [_clean(order_id) for (order_id,) in rows if _clean(order_id)]


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
    operational = db.session.execute(
        text(
            """
            SELECT shipping_service, ship_by_at, earliest_delivery_at,
                   latest_delivery_at, marketplace_checked_at
            FROM fbm_order_operational_state
            WHERE store_id = :store_id AND marketplace_order_id = :order_id
            LIMIT 1
            """
        ),
        {"store_id": int(store_id), "order_id": order_id},
    ).mappings().first()
    spend = db.session.execute(
        text(
            """
            SELECT provider, amount, currency, source, source_reference,
                   confirmed, recorded_at
            FROM shipping_spend_ledger
            WHERE store_id = :store_id
              AND marketplace_order_id = :order_id
              AND confirmed = TRUE
            ORDER BY recorded_at DESC NULLS LAST, id DESC
            LIMIT 1
            """
        ),
        {"store_id": int(store_id), "order_id": order_id},
    ).mappings().first()
    shipment = db.session.execute(
        text(
            """
            SELECT id, provider, carrier, service, tracking_number,
                   status, label_purchased_at, handover_due_at,
                   carrier_accepted_at, first_movement_at, delivered_at,
                   last_provider_status, last_provider_checked_at,
                   marketplace_confirmed_at, marketplace_confirmation_status
            FROM fbm_shipments
            WHERE store_id = :store_id AND marketplace_order_id = :order_id
            ORDER BY id DESC
            LIMIT 1
            """
        ),
        {"store_id": int(store_id), "order_id": order_id},
    ).mappings().first()

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
        "shipping_service": operational.get("shipping_service") if operational else None,
        "ship_by_at": operational.get("ship_by_at") if operational else None,
        "earliest_delivery_at": operational.get("earliest_delivery_at") if operational else None,
        "latest_delivery_at": operational.get("latest_delivery_at") if operational else None,
        "marketplace_checked_at": operational.get("marketplace_checked_at") if operational else None,
        "confirmed_shipping_spend": dict(spend) if spend else None,
        "fbm_shipment": dict(shipment) if shipment else None,
    }


def _recover_amazon(store: Store, order_id: str) -> dict[str, Any]:
    from services.fbm_amazon_order_profile import get_or_refresh_amazon_profile
    from services.governed_amazon_tracking_readback import hydrate_amazon_tracking_for_order

    order = (
        MarketplaceOrder.query
        .filter(
            MarketplaceOrder.store_id == int(store.id),
            MarketplaceOrder.marketplace_order_id == order_id,
        )
        .order_by(MarketplaceOrder.id.desc())
        .first()
    )
    if order is None:
        return {
            "success": False,
            "reason": "amazon_existing_order_not_found",
            "marketplace_write_started": False,
        }

    profile_error = None
    try:
        get_or_refresh_amazon_profile(order, force=True)
        profile_success = True
    except Exception as exc:
        db.session.rollback()
        profile_success = False
        profile_error = str(exc)[:1000]

    tracking = hydrate_amazon_tracking_for_order(
        store=store,
        marketplace_order_id=order_id,
        source="operator_dispatch_history_recovery",
    )
    db.session.expire_all()
    readback = _database_readback(store.id, order_id)

    return {
        "success": bool(profile_success or tracking.get("success")),
        "profile_promise_readback": {
            "success": profile_success,
            "error": profile_error,
        },
        "tracking_readback": tracking,
        "shipping_label_readback": None,
        "amazon_label_cost_excluded": True,
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
        "amazon_label_cost_excluded": True,
        "stores": [],
    }
    totals = defaultdict(int)

    for store in stores:
        platform = _platform(store)
        if platform not in {"amazon", "ebay"}:
            continue

        first_dispatch_at = _first_dispatch_at(store.id)
        order_ids = _candidate_order_ids(store.id, platform=platform)
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
            tracking_resolved = bool(readback.get("tracking_number") and readback.get("carrier"))
            promise_available = bool(
                readback.get("ship_by_at") is not None
                and (
                    readback.get("earliest_delivery_at") is not None
                    or readback.get("latest_delivery_at") is not None
                )
            )
            spend_available = bool(readback.get("confirmed_shipping_spend"))
            fbm_shipment_available = bool(readback.get("fbm_shipment"))

            if platform == "ebay":
                hydration = result.get("hydration") if isinstance(result, dict) else None
                finance = hydration.get("shipping_label_finance") if isinstance(hydration, dict) else None
                exact_finance_checked = bool(
                    isinstance(finance, dict)
                    and finance.get("success") is True
                    and not finance.get("skipped")
                )
                label_purchase_confirmed = bool(
                    isinstance(finance, dict) and finance.get("purchase_confirmed") is True
                )
                extraction_resolved = bool(
                    tracking_resolved
                    and promise_available
                    and (
                        spend_available
                        or (exact_finance_checked and not label_purchase_confirmed)
                    )
                )
            else:
                exact_finance_checked = False
                label_purchase_confirmed = False
                extraction_resolved = bool(tracking_resolved and promise_available)

            if extraction_resolved:
                store_result["resolved"] += 1
                totals["resolved"] += 1
            elif not result.get("success"):
                store_result["failed"] += 1
                totals["failed"] += 1
            else:
                store_result["still_missing"] += 1
                totals["still_missing"] += 1

            store_result["orders"].append({
                "order_id": order_id,
                "success": bool(result.get("success")),
                "resolved": extraction_resolved,
                "tracking_resolved": tracking_resolved,
                "delivery_promise_available": promise_available,
                "confirmed_shipping_spend_available": spend_available if platform == "ebay" else None,
                "fbm_shipment_available": fbm_shipment_available,
                "exact_finance_checked": exact_finance_checked,
                "label_purchase_confirmed": label_purchase_confirmed,
                "amazon_label_cost_excluded": platform == "amazon",
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
    from app import app

    with app.app_context():
        print(json.dumps(recover_missing_dispatch_truth_from_db_start(), default=str))
