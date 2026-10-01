"""One-shot delivery-deadline recovery for confirmed eBay Buy Shipping only.

This wraps the existing exact eBay hydration after its finance/shipment authority
alignment. It queues one exact-order runtime event for the end of the persisted
eBay delivery promise. No poller, recurring scan, marketplace write, or second
shipment writer is introduced.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import text

from extensions import db
from services import governed_exact_ebay_order_hydration as _exact


_ORIGINAL = _exact.hydrate_exact_ebay_order
_INSTALLED = False
_RUNTIME_ORIGINAL_START = None


def _queue_deadline(*, store, order_id: str) -> dict:
    row = db.session.execute(
        text(
            """
            SELECT os.latest_delivery_at, os.marketplace_checked_at
            FROM fbm_order_operational_state os
            WHERE os.store_id = :store_id
              AND os.marketplace_order_id = :order_id
              AND os.platform = 'ebay'
              AND os.latest_delivery_at IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM fbm_shipments fs
                  WHERE fs.store_id = os.store_id
                    AND fs.marketplace_order_id = os.marketplace_order_id
                    AND fs.provider = 'ebay_shipping'
                    AND fs.delivered_at IS NULL
              )
              AND EXISTS (
                  SELECT 1 FROM shipping_spend_ledger ssl
                  WHERE ssl.store_id = os.store_id
                    AND ssl.marketplace_order_id = os.marketplace_order_id
                    AND ssl.provider = 'ebay'
                    AND ssl.source = 'ebay_finances_shipping_label'
                    AND ssl.confirmed = TRUE
              )
            LIMIT 1
            """
        ),
        {"store_id": int(store.id), "order_id": str(order_id)},
    ).mappings().first()
    if not row:
        return {"queued": False, "reason": "confirmed_ebay_buy_shipping_deadline_not_eligible"}

    latest = row["latest_delivery_at"]
    due_at = datetime.combine(latest.date() + timedelta(days=1), datetime.min.time())
    checked_at = row.get("marketplace_checked_at")
    if checked_at is not None and checked_at >= due_at:
        return {"queued": False, "reason": "delivery_deadline_already_checked"}

    from services.governed_runtime_engine import notify_governed_runtime_work

    return notify_governed_runtime_work(
        source="ebay_buy_shipping_delivery_deadline",
        event={
            "event_type": "ebay_buy_shipping_delivery_deadline",
            "marketplace": "ebay",
            "store_id": int(store.id),
            "order_id": str(order_id),
            "verify_after": max(due_at, datetime.utcnow()),
            "payload": {
                "authority": "confirmed_ebay_buy_shipping",
                "latest_delivery_at": latest.isoformat(),
            },
        },
    )


def _aligned_hydrate(*, store, marketplace_order_id: str, source: str):
    result = _ORIGINAL(
        store=store,
        marketplace_order_id=marketplace_order_id,
        source=source,
    )
    if isinstance(result, dict):
        finance = result.get("shipping_label_finance") or {}
        shipment = result.get("shipping_label_shipment_authority") or {}
        if finance.get("purchase_confirmed") is True and shipment.get("success") is True:
            result["buy_shipping_delivery_deadline_recovery"] = _queue_deadline(
                store=store,
                order_id=marketplace_order_id,
            )
        else:
            result["buy_shipping_delivery_deadline_recovery"] = {
                "queued": False,
                "reason": "confirmed_ebay_buy_shipping_required",
            }
    return result



def _restore_pending_deadlines(app) -> int:
    """Bounded restart recovery only; never runs as a recurring scan."""
    rows = db.session.execute(
        text(
            """
            SELECT DISTINCT os.store_id, os.marketplace_order_id
            FROM fbm_order_operational_state os
            WHERE os.platform = 'ebay'
              AND os.latest_delivery_at IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM fbm_shipments fs
                  WHERE fs.store_id = os.store_id
                    AND fs.marketplace_order_id = os.marketplace_order_id
                    AND fs.provider = 'ebay_shipping'
                    AND fs.delivered_at IS NULL
              )
              AND EXISTS (
                  SELECT 1 FROM shipping_spend_ledger ssl
                  WHERE ssl.store_id = os.store_id
                    AND ssl.marketplace_order_id = os.marketplace_order_id
                    AND ssl.provider = 'ebay'
                    AND ssl.source = 'ebay_finances_shipping_label'
                    AND ssl.confirmed = TRUE
              )
            ORDER BY os.store_id, os.marketplace_order_id
            LIMIT 250
            """
        )
    ).mappings().all()

    from models import Store

    queued = 0
    for row in rows:
        store = db.session.get(Store, int(row["store_id"]))
        if store is None:
            continue
        result = _queue_deadline(
            store=store,
            order_id=str(row["marketplace_order_id"]),
        )
        if result.get("queued"):
            queued += 1
    return queued


def _start_with_deadline_restore(app):
    started = _RUNTIME_ORIGINAL_START(app)
    if not started:
        return started
    try:
        with app.app_context():
            _restore_pending_deadlines(app)
    except Exception:
        # Restart recovery is best-effort; the governed runtime itself remains live.
        pass
    return started


def install() -> None:
    global _INSTALLED, _RUNTIME_ORIGINAL_START
    if _INSTALLED:
        return
    _exact.hydrate_exact_ebay_order = _aligned_hydrate

    import services.governed_runtime_engine as runtime
    _RUNTIME_ORIGINAL_START = runtime.start_governed_runtime_engine
    runtime.start_governed_runtime_engine = _start_with_deadline_restore
    _INSTALLED = True


install()
