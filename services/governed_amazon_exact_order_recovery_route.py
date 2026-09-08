"""Authenticated exact Amazon FBM lifecycle recovery route.

This is a narrow operator recovery surface for one existing Amazon FBM order.
It reuses the existing Amazon Orders v2026 exact readback and existing Seller
Central purchased-label readback. It persists only Amazon-owned lifecycle,
tracking and validated shipment authority into existing BT38 records. It never
creates/replays an order, mutates inventory, buys postage, confirms shipment to
Amazon, starts a scan, scheduler, or marketplace write.
"""
from __future__ import annotations

import hmac
import os
import re

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user

from extensions import db
from models import MarketplaceOrder, Store
from services.governed_amazon_shipping_label_readback import (
    hydrate_amazon_purchased_label_for_order,
)
from services.governed_amazon_tracking_readback import hydrate_amazon_tracking_for_order


governed_amazon_exact_order_recovery_bp = Blueprint(
    "governed_amazon_exact_order_recovery",
    __name__,
)

_AMAZON_ORDER_RE = re.compile(r"\d{3}-\d{7}-\d{7}")


def _operator_authorized() -> bool:
    configured_task_key = str(os.environ.get("TASK_API_KEY") or "")
    supplied_task_key = str(request.headers.get("X-Task-Key") or "")
    session_authorized = bool(getattr(current_user, "is_authenticated", False))
    task_authorized = bool(
        configured_task_key
        and supplied_task_key
        and hmac.compare_digest(configured_task_key, supplied_task_key)
    )
    return bool(session_authorized or task_authorized)


@governed_amazon_exact_order_recovery_bp.post(
    "/governed/actions/amazon/exact-order-recovery"
)
def recover_exact_amazon_order_manually():
    """Refresh exact Amazon-owned truth for one existing Amazon FBM order only."""
    if not _operator_authorized():
        return jsonify({
            "success": False,
            "ok": False,
            "governed": True,
            "reason": "authentication_required",
            "marketplace_write_started": False,
        }), 401

    payload = request.get_json(silent=True) or {}
    try:
        store_id = int(payload.get("store_id"))
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "ok": False,
            "governed": True,
            "reason": "invalid_store_id",
            "marketplace_write_started": False,
        }), 400

    order_id = str(payload.get("marketplace_order_id") or "").strip()
    if store_id <= 0 or not _AMAZON_ORDER_RE.fullmatch(order_id):
        return jsonify({
            "success": False,
            "ok": False,
            "governed": True,
            "reason": "invalid_exact_amazon_order_identity",
            "marketplace_write_started": False,
        }), 400

    store = db.session.get(Store, store_id)
    if (
        store is None
        or not bool(getattr(store, "is_active", False))
        or "amazon" not in str(getattr(store, "platform", "") or "").lower()
    ):
        return jsonify({
            "success": False,
            "ok": False,
            "governed": True,
            "reason": "active_amazon_store_not_found",
            "store_id": store_id,
            "marketplace_write_started": False,
        }), 404

    rows = (
        MarketplaceOrder.query
        .filter(
            MarketplaceOrder.store_id == store_id,
            MarketplaceOrder.marketplace_order_id == order_id,
        )
        .order_by(MarketplaceOrder.id)
        .all()
    )
    eligible = [
        row for row in rows
        if str(getattr(row, "fulfillment_type", "") or "").strip().upper()
        not in {"FBA", "AFN", "MCF"}
        and not str(getattr(row, "status", "") or "").strip().lower().startswith("mcf_")
    ]
    if not eligible:
        return jsonify({
            "success": False,
            "ok": False,
            "governed": True,
            "reason": "existing_amazon_fbm_order_missing",
            "store_id": store_id,
            "order_id": order_id,
            "exact_order_only": True,
            "order_replayed": False,
            "stock_mutation_started": False,
            "marketplace_write_started": False,
        }), 404

    try:
        result = hydrate_amazon_tracking_for_order(
            store=store,
            marketplace_order_id=order_id,
            source="manual_exact_amazon_recovery",
        )
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception(
            "BT38 manual exact Amazon recovery failed store_id=%s order_id=%s",
            store_id,
            order_id,
        )
        return jsonify({
            "success": False,
            "ok": False,
            "governed": True,
            "reason": "exact_amazon_recovery_exception",
            "error": str(exc)[:500],
            "store_id": store_id,
            "order_id": order_id,
            "exact_order_only": True,
            "broad_scan_started": False,
            "order_replayed": False,
            "stock_mutation_started": False,
            "marketplace_write_started": False,
        }), 502

    try:
        shipping_label = hydrate_amazon_purchased_label_for_order(
            store=store,
            marketplace_order_id=order_id,
            source="manual_exact_amazon_recovery",
        )
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception(
            "BT38 manual exact Amazon purchased-label recovery failed store_id=%s order_id=%s",
            store_id,
            order_id,
        )
        shipping_label = {
            "success": False,
            "skipped": False,
            "reason": "amazon_purchased_label_recovery_exception",
            "error": str(exc)[:500],
            "order_id": order_id,
            "marketplace_write_started": False,
        }

    hydration = dict(result)
    hydration["shipping_label"] = shipping_label

    db.session.expire_all()
    readback_rows = (
        MarketplaceOrder.query
        .filter(
            MarketplaceOrder.store_id == store_id,
            MarketplaceOrder.marketplace_order_id == order_id,
        )
        .order_by(MarketplaceOrder.id)
        .all()
    )
    readback = [
        {
            "id": int(row.id),
            "status": row.status,
            "carrier": row.carrier,
            "tracking_number": row.tracking_number,
            "shipped_at": row.shipped_at.isoformat() if row.shipped_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in readback_rows
    ]

    return jsonify({
        "success": bool(result.get("success")),
        "ok": bool(result.get("success")),
        "governed": True,
        "exact_order_only": True,
        "broad_scan_started": False,
        "order_replayed": False,
        "stock_mutation_started": False,
        "marketplace_write_started": False,
        "store_id": store_id,
        "order_id": order_id,
        "hydration": hydration,
        "database_readback": readback,
    }), 200


@governed_amazon_exact_order_recovery_bp.post(
    "/governed/actions/marketplace/dispatch-history-recovery"
)
def recover_marketplace_dispatch_history_manually():
    """Run the explicit one-time Amazon/eBay missing dispatch truth recovery."""
    if not _operator_authorized():
        return jsonify({
            "success": False,
            "ok": False,
            "governed": True,
            "reason": "authentication_required",
            "polling_started": False,
            "marketplace_write_started": False,
        }), 401

    payload = request.get_json(silent=True) or {}
    if str(payload.get("confirm") or "").strip() != "RECOVER_DB_DISPATCH_HISTORY":
        return jsonify({
            "success": False,
            "ok": False,
            "governed": True,
            "reason": "explicit_confirmation_required",
            "required_confirmation": "RECOVER_DB_DISPATCH_HISTORY",
            "polling_started": False,
            "marketplace_write_started": False,
        }), 400

    from scripts.recover_marketplace_dispatch_history import (
        recover_missing_dispatch_truth_from_db_start,
    )

    try:
        result = recover_missing_dispatch_truth_from_db_start()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("BT38 dispatch history recovery failed")
        return jsonify({
            "success": False,
            "ok": False,
            "governed": True,
            "reason": "dispatch_history_recovery_exception",
            "error": str(exc)[:1000],
            "polling_started": False,
            "scheduler_started": False,
            "worker_started": False,
            "marketplace_write_started": False,
        }), 502

    stores = [
        {
            "store_id": item.get("store_id"),
            "store_name": item.get("store_name"),
            "platform": item.get("platform"),
            "first_dispatch_at": item.get("first_dispatch_at"),
            "candidate_orders": item.get("candidate_orders"),
            "resolved": item.get("resolved"),
            "still_missing": item.get("still_missing"),
            "failed": item.get("failed"),
        }
        for item in result.get("stores", [])
    ]

    return jsonify({
        "success": bool(result.get("success")),
        "ok": bool(result.get("success")),
        "governed": True,
        "operator_action": True,
        "automatic_startup_recovery": False,
        "polling_started": False,
        "scheduler_started": False,
        "worker_started": False,
        "marketplace_write_started": False,
        "selected": int(result.get("selected", 0)),
        "resolved": int(result.get("resolved", 0)),
        "still_missing": int(result.get("still_missing", 0)),
        "failed": int(result.get("failed", 0)),
        "stores": stores,
    }), 200
