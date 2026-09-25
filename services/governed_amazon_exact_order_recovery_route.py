"""Authenticated exact marketplace journey recovery routes.

The single-order actions reuse existing governed marketplace authorities. Recovery
means the complete available persisted shipment journey for the exact order:
tracking identity, package/carrier events, milestones, promise and purchased-label
truth where already supported. FBA/AFN keeps its finite historical helper and MCF
remains excluded. No broad scan, inventory mutation, marketplace write, worker,
poller or scheduler is introduced by an exact-order action.
"""
from __future__ import annotations

import hmac
import os
import re

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user
from sqlalchemy import text

from extensions import db
from models import MarketplaceOrder, Store
from services.governed_amazon_shipping_label_readback import hydrate_amazon_purchased_label_for_order
from services.governed_amazon_tracking_readback import hydrate_amazon_tracking_for_order
from services.governed_amazon_fbm_profile_event_alignment import refresh_exact_amazon_order


governed_amazon_exact_order_recovery_bp = Blueprint("governed_amazon_exact_order_recovery", __name__)
_AMAZON_ORDER_RE = re.compile(r"\d{3}-\d{7}-\d{7}")
_FBA_TYPES = {"FBA", "AFN"}


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


def _readback(store_id: int, order_id: str) -> list[dict]:
    db.session.expire_all()
    rows = (
        MarketplaceOrder.query
        .filter(
            MarketplaceOrder.store_id == store_id,
            MarketplaceOrder.marketplace_order_id == order_id,
        )
        .order_by(MarketplaceOrder.id)
        .all()
    )
    return [
        {
            "id": int(row.id),
            "fulfillment_type": row.fulfillment_type,
            "status": row.status,
            "carrier": row.carrier,
            "tracking_number": row.tracking_number,
            "shipped_at": row.shipped_at.isoformat() if row.shipped_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in rows
    ]


@governed_amazon_exact_order_recovery_bp.post("/governed/actions/marketplace/exact-order-recovery-check")
def check_exact_marketplace_order_recovery():
    """DB-only gate for Recover Missing; never contacts a marketplace."""
    if not _operator_authorized():
        return jsonify({
            "success": False, "ok": False, "governed": True,
            "reason": "authentication_required", "marketplace_call_started": False,
        }), 401

    payload = request.get_json(silent=True) or {}
    try:
        store_id = int(payload.get("store_id"))
    except (TypeError, ValueError):
        return jsonify({
            "success": False, "ok": False, "governed": True,
            "reason": "invalid_store_id", "marketplace_call_started": False,
        }), 400

    order_id = str(payload.get("marketplace_order_id") or "").strip()
    platform = str(payload.get("platform") or "").strip().lower()
    if store_id <= 0 or not order_id or platform not in {"amazon", "ebay"}:
        return jsonify({
            "success": False, "ok": False, "governed": True,
            "reason": "invalid_exact_recovery_identity", "marketplace_call_started": False,
        }), 400

    store = db.session.get(Store, store_id)
    if (
        store is None
        or not bool(getattr(store, "is_active", False))
        or platform not in str(getattr(store, "platform", "") or "").lower()
    ):
        return jsonify({
            "success": False, "ok": False, "governed": True,
            "reason": "active_store_not_found", "marketplace_call_started": False,
        }), 404

    from scripts.recover_marketplace_dispatch_history import (
        _candidate_order_ids,
        _database_readback,
    )

    before = _database_readback(store_id, order_id)
    candidates = set(_candidate_order_ids(store_id, platform=platform))
    recovery_required = order_id in candidates

    # eBay journey evidence is part of recovery completeness.  The proven exact
    # eBay readback persists supported marketplace events (Sell Fulfillment
    # shippedDate and Trading GetOrders ActualDeliveryTime) into the canonical
    # tracking-event ledger.  Do not declare an order complete merely because
    # carrier/tracking/promise/spend already exist.
    ebay_event_evidence = None
    if platform == "ebay":
        ebay_event_evidence = db.session.execute(
            text(
                """
                SELECT
                    COUNT(fte.id) AS event_count,
                    COUNT(fte.id) FILTER (WHERE LOWER(COALESCE(fte.status, '')) = 'shipped') AS shipped_count,
                    COUNT(fte.id) FILTER (WHERE LOWER(COALESCE(fte.status, '')) = 'delivered') AS delivered_count
                FROM fbm_shipments fs
                LEFT JOIN fbm_shipment_tracking_events fte
                  ON fte.shipment_id = fs.id
                 AND fte.provider = 'ebay'
                WHERE fs.store_id = :store_id
                  AND fs.marketplace_order_id = :order_id
                  AND fs.provider = 'ebay_shipping'
                """
            ),
            {"store_id": store_id, "order_id": order_id},
        ).mappings().first()
        shipment_truth = before.get("fbm_shipment") or {}
        event_count = int((ebay_event_evidence or {}).get("event_count") or 0)
        shipped_count = int((ebay_event_evidence or {}).get("shipped_count") or 0)
        delivered_count = int((ebay_event_evidence or {}).get("delivered_count") or 0)
        if shipment_truth and (event_count == 0 or shipped_count == 0):
            recovery_required = True
        if shipment_truth.get("delivered_at") is not None and delivered_count == 0:
            recovery_required = True

    missing = []
    if not before.get("tracking_number"):
        missing.append("tracking")
    if not before.get("carrier"):
        missing.append("carrier")
    if before.get("ship_by_at") is None:
        missing.append("ship-by promise")
    if before.get("earliest_delivery_at") is None and before.get("latest_delivery_at") is None:
        missing.append("delivery promise")
    if platform == "ebay" and not before.get("confirmed_shipping_spend"):
        missing.append("confirmed shipping spend")
    if platform == "ebay":
        shipment_truth = before.get("fbm_shipment") or {}
        event_count = int((ebay_event_evidence or {}).get("event_count") or 0)
        shipped_count = int((ebay_event_evidence or {}).get("shipped_count") or 0)
        delivered_count = int((ebay_event_evidence or {}).get("delivered_count") or 0)
        if shipment_truth and (event_count == 0 or shipped_count == 0):
            missing.append("eBay shipped event evidence")
        if shipment_truth.get("delivered_at") is not None and delivered_count == 0:
            missing.append("eBay delivered event evidence")
    if platform == "amazon" and recovery_required and not missing:
        missing.append("Amazon tracking event history")

    return jsonify({
        "success": True, "ok": True, "governed": True,
        "db_check_completed": True, "marketplace_call_started": False,
        "store_id": store_id, "order_id": order_id, "platform": platform,
        "recovery_required": recovery_required, "missing": missing,
        "ebay_event_evidence": dict(ebay_event_evidence) if ebay_event_evidence is not None else None,
        "database_readback": before,
    }), 200


@governed_amazon_exact_order_recovery_bp.post("/governed/actions/amazon/exact-order-recovery")
def recover_exact_amazon_order_manually():
    """Recover the complete available Amazon-owned journey for one exact order."""
    if not _operator_authorized():
        return jsonify({
            "success": False, "ok": False, "governed": True,
            "reason": "authentication_required", "marketplace_write_started": False,
        }), 401

    payload = request.get_json(silent=True) or {}
    try:
        store_id = int(payload.get("store_id"))
    except (TypeError, ValueError):
        return jsonify({
            "success": False, "ok": False, "governed": True,
            "reason": "invalid_store_id", "marketplace_write_started": False,
        }), 400

    order_id = str(payload.get("marketplace_order_id") or "").strip()
    if store_id <= 0 or not _AMAZON_ORDER_RE.fullmatch(order_id):
        return jsonify({
            "success": False, "ok": False, "governed": True,
            "reason": "invalid_exact_amazon_order_identity", "marketplace_write_started": False,
        }), 400

    store = db.session.get(Store, store_id)
    if (
        store is None
        or not bool(getattr(store, "is_active", False))
        or "amazon" not in str(getattr(store, "platform", "") or "").lower()
    ):
        return jsonify({
            "success": False, "ok": False, "governed": True,
            "reason": "active_amazon_store_not_found", "store_id": store_id,
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
    fba_rows = [
        row for row in rows
        if str(getattr(row, "fulfillment_type", "") or "").strip().upper() in _FBA_TYPES
    ]
    fbm_rows = [
        row for row in rows
        if str(getattr(row, "fulfillment_type", "") or "").strip().upper()
        not in {"FBA", "AFN", "MCF"}
        and not str(getattr(row, "status", "") or "").strip().lower().startswith("mcf_")
    ]

    if fba_rows:
        try:
            from services.governed_fba_historical_recovery import recover_exact_fba_order
            result = recover_exact_fba_order(store=store, marketplace_order_id=order_id)
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception(
                "BT38 manual exact Amazon FBA recovery failed store_id=%s order_id=%s",
                store_id, order_id,
            )
            return jsonify({
                "success": False, "ok": False, "governed": True,
                "reason": "exact_amazon_fba_recovery_exception", "error": str(exc)[:500],
                "store_id": store_id, "order_id": order_id, "fulfillment_type": "FBA",
                "exact_order_only": True, "broad_scan_started": False,
                "order_replayed": False, "stock_mutation_started": False,
                "warehouse_mutation_started": False, "group_propagation_started": False,
                "marketplace_write_started": False, "polling_started": False,
                "worker_started": False,
            }), 502

        return jsonify({
            "success": bool(result.get("success")), "ok": bool(result.get("success")),
            "governed": True, "fulfillment_type": "FBA", "exact_order_only": True,
            "broad_scan_started": False, "order_replayed": False,
            "stock_mutation_started": False, "warehouse_mutation_started": False,
            "group_propagation_started": False, "marketplace_write_started": False,
            "polling_started": False, "worker_started": False,
            "store_id": store_id, "order_id": order_id,
            "recovery": result, "database_readback": _readback(store_id, order_id),
        }), 200

    if not fbm_rows:
        return jsonify({
            "success": False, "ok": False, "governed": True,
            "reason": "existing_amazon_order_missing_or_mcf", "store_id": store_id,
            "order_id": order_id, "exact_order_only": True, "order_replayed": False,
            "stock_mutation_started": False, "marketplace_write_started": False,
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
            "BT38 manual exact Amazon recovery failed store_id=%s order_id=%s", store_id, order_id,
        )
        return jsonify({
            "success": False, "ok": False, "governed": True,
            "reason": "exact_amazon_recovery_exception", "error": str(exc)[:500],
            "store_id": store_id, "order_id": order_id, "exact_order_only": True,
            "broad_scan_started": False, "order_replayed": False,
            "stock_mutation_started": False, "marketplace_write_started": False,
        }), 502

    try:
        promise_readback = [refresh_exact_amazon_order(row) for row in fbm_rows]
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception(
            "BT38 manual exact Amazon promise recovery failed store_id=%s order_id=%s", store_id, order_id,
        )
        return jsonify({
            "success": False, "ok": False, "governed": True,
            "reason": "exact_amazon_promise_recovery_exception", "error": str(exc)[:500],
            "store_id": store_id, "order_id": order_id, "exact_order_only": True,
            "broad_scan_started": False, "order_replayed": False,
            "stock_mutation_started": False, "marketplace_write_started": False,
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
            store_id, order_id,
        )
        shipping_label = {
            "success": False, "skipped": False,
            "reason": "amazon_purchased_label_recovery_exception",
            "error": str(exc)[:500], "order_id": order_id,
            "marketplace_write_started": False,
        }

    hydration = dict(result)
    hydration["promise_readback"] = promise_readback
    hydration["shipping_label"] = shipping_label
    return jsonify({
        "success": bool(result.get("success")), "ok": bool(result.get("success")),
        "governed": True, "fulfillment_type": "FBM", "exact_order_only": True,
        "broad_scan_started": False, "order_replayed": False,
        "stock_mutation_started": False, "marketplace_write_started": False,
        "store_id": store_id, "order_id": order_id,
        "hydration": hydration,
        "shipping_cost_recovery": {
            "attempted": True,
            "source": "existing_amazon_purchased_label_readback",
            "shipping_cost_persisted": bool(shipping_label.get("shipping_cost_persisted")),
            "shipping_cost": shipping_label.get("shipping_cost"),
            "shipping_cost_currency": shipping_label.get("shipping_cost_currency"),
        },
        "database_readback": _readback(store_id, order_id),
    }), 200


@governed_amazon_exact_order_recovery_bp.post("/governed/actions/marketplace/dispatch-history-recovery")
def recover_marketplace_dispatch_history_manually():
    """Run the explicit one-time Amazon/eBay missing dispatch truth recovery."""
    if not _operator_authorized():
        return jsonify({
            "success": False, "ok": False, "governed": True,
            "reason": "authentication_required", "polling_started": False,
            "marketplace_write_started": False,
        }), 401

    payload = request.get_json(silent=True) or {}
    if str(payload.get("confirm") or "").strip() != "RECOVER_DB_DISPATCH_HISTORY":
        return jsonify({
            "success": False, "ok": False, "governed": True,
            "reason": "explicit_confirmation_required",
            "required_confirmation": "RECOVER_DB_DISPATCH_HISTORY",
            "polling_started": False, "marketplace_write_started": False,
        }), 400

    from scripts.recover_marketplace_dispatch_history import recover_missing_dispatch_truth_from_db_start
    try:
        result = recover_missing_dispatch_truth_from_db_start()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("BT38 dispatch history recovery failed")
        return jsonify({
            "success": False, "ok": False, "governed": True,
            "reason": "dispatch_history_recovery_exception", "error": str(exc)[:1000],
            "polling_started": False, "scheduler_started": False,
            "worker_started": False, "marketplace_write_started": False,
        }), 502

    stores, failures, unresolved = [], [], []
    for item in result.get("stores", []):
        stores.append({
            "store_id": item.get("store_id"), "store_name": item.get("store_name"),
            "platform": item.get("platform"), "first_dispatch_at": item.get("first_dispatch_at"),
            "candidate_orders": item.get("candidate_orders"), "resolved": item.get("resolved"),
            "still_missing": item.get("still_missing"), "failed": item.get("failed"),
        })
        for order in item.get("orders", []):
            evidence = {
                "store_id": item.get("store_id"), "store_name": item.get("store_name"),
                "platform": item.get("platform"), "order_id": order.get("order_id"),
                "success": bool(order.get("success")), "resolved": bool(order.get("resolved")),
                "database_readback": order.get("database_readback"), "result": order.get("result"),
            }
            if not order.get("resolved") and not order.get("success"):
                failures.append(evidence)
            elif not order.get("resolved"):
                unresolved.append(evidence)

    return jsonify({
        "success": bool(result.get("success")), "ok": bool(result.get("success")),
        "governed": True, "operator_action": True, "automatic_startup_recovery": False,
        "polling_started": False, "scheduler_started": False, "worker_started": False,
        "marketplace_write_started": False, "selected": int(result.get("selected", 0)),
        "resolved": int(result.get("resolved", 0)), "still_missing": int(result.get("still_missing", 0)),
        "failed": int(result.get("failed", 0)), "stores": stores,
        "failures": failures, "unresolved": unresolved,
    }), 200
