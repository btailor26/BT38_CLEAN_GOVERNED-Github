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

    # Canonical Data Truth Review owns the definition of known/missing/unverified.
    # Recovery is a consumer of this DB-derived manifest; the browser must not
    # invent a separate truth-gap model.
    from services.governed_fbm_data_truth_review import review_fbm_data_truth
    truth_review = review_fbm_data_truth(
        store_id=store_id,
        order_id=order_id,
        platform=platform,
        readback=before,
    )
    recovery_required = bool(truth_review["recovery_required"])
    missing = list(truth_review["missing"])
    unverified = list(truth_review["unverified"])

    # eBay's supported marketplace readback cannot independently prove carrier
    # pickup/movement scans. Keep that capability fact visible; other connected
    # shipping authorities may still be eligible to recover those DB gaps.
    unavailable_tracking_evidence = []
    if platform == "ebay":
        shipment_truth = before.get("fbm_shipment") or {}
        if shipment_truth and before.get("tracking_number"):
            milestones = db.session.execute(
                text("""
                    SELECT
                        COUNT(fte.id) FILTER (
                            WHERE LOWER(COALESCE(fte.status, '')) IN
                                ('carrier_accepted', 'accepted', 'picked_up', 'collected')
                        ) AS accepted_count,
                        COUNT(fte.id) FILTER (
                            WHERE LOWER(COALESCE(fte.status, '')) IN
                                ('in_transit', 'out_for_delivery', 'in transit')
                        ) AS movement_count
                    FROM fbm_shipments fs
                    LEFT JOIN fbm_shipment_tracking_events fte
                      ON fte.shipment_id = fs.id
                    WHERE fs.store_id = :store_id
                      AND fs.marketplace_order_id = :order_id
                """),
                {"store_id": store_id, "order_id": order_id},
            ).mappings().first()
            if not shipment_truth.get("carrier_accepted_at") and not int((milestones or {}).get("accepted_count") or 0):
                unavailable_tracking_evidence.append("carrier pickup scan")
            if not shipment_truth.get("first_movement_at") and not int((milestones or {}).get("movement_count") or 0):
                unavailable_tracking_evidence.append("in-transit carrier scan")

    return jsonify({
        "success": True, "ok": True, "governed": True,
        "db_check_completed": True, "marketplace_call_started": False,
        "store_id": store_id, "order_id": order_id, "platform": platform,
        "recovery_required": recovery_required, "missing": missing, "unverified": unverified,
        "truth_review": truth_review,
        "unavailable_tracking_evidence": unavailable_tracking_evidence,
        "carrier_history_supported_by_exact_ebay_readback": False if platform == "ebay" else None,
        "ebay_event_evidence": dict(ebay_event_evidence) if ebay_event_evidence is not None else None,
        "database_readback": before,
    }), 200


@governed_amazon_exact_order_recovery_bp.post("/governed/actions/amazon/exact-order-recovery")
def recover_exact_amazon_order_manually():
    """DB-first exact Amazon recovery: call only authorities required by persisted gaps."""
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

    # DB is the authority. Build the recovery plan from persisted Data Truth before
    # any provider call. A provider is contacted only for a gap it can fill.
    from scripts.recover_marketplace_dispatch_history import _database_readback
    from services.governed_fbm_data_truth_review import review_fbm_data_truth

    before = _database_readback(store_id, order_id)
    before_review = review_fbm_data_truth(
        store_id=store_id, order_id=order_id, platform="amazon", readback=before,
    )
    gaps = set(before_review.get("missing") or []) | set(before_review.get("unverified") or [])

    tracking_gaps = {"tracking_number", "tracking_history", "carrier"}
    promise_gaps = {"ship_by_promise", "delivery_promise"}
    label_gaps = {"provider_reference", "shipping_fee"}

    calls_started = []
    tracking_result = {"success": True, "skipped": True, "reason": "db_truth_complete"}
    promise_readback = []
    shipping_label = {"success": True, "skipped": True, "reason": "db_truth_complete"}

    if gaps & tracking_gaps:
        calls_started.append("amazon_tracking")
        try:
            tracking_result = hydrate_amazon_tracking_for_order(
                store=store,
                marketplace_order_id=order_id,
                source="manual_exact_amazon_recovery",
            )
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception(
                "BT38 manual exact Amazon tracking recovery failed store_id=%s order_id=%s",
                store_id, order_id,
            )
            return jsonify({
                "success": False, "ok": False, "governed": True,
                "reason": "exact_amazon_tracking_recovery_exception", "error": str(exc)[:500],
                "store_id": store_id, "order_id": order_id, "exact_order_only": True,
                "db_check_completed": True, "gaps_before": sorted(gaps),
                "calls_started": calls_started, "marketplace_write_started": False,
            }), 502
        if not bool(tracking_result.get("success")):
            upstream_status = tracking_result.get("status_code")
            try:
                response_status = int(upstream_status)
            except (TypeError, ValueError):
                response_status = 502
            if response_status < 400 or response_status > 599:
                response_status = 502
            return jsonify({
                "success": False, "ok": False, "governed": True,
                "reason": tracking_result.get("reason") or "amazon_exact_tracking_recovery_failed",
                "error": tracking_result.get("error"), "status_code": upstream_status,
                "store_id": store_id, "order_id": order_id, "fulfillment_type": "FBM",
                "exact_order_only": True, "db_check_completed": True,
                "gaps_before": sorted(gaps), "calls_started": calls_started,
                "marketplace_write_started": False,
                "tracking_recovery": tracking_result,
            }), response_status

    if gaps & promise_gaps:
        calls_started.append("amazon_promise")
        try:
            promise_readback = [refresh_exact_amazon_order(row) for row in fbm_rows]
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception(
                "BT38 manual exact Amazon promise recovery failed store_id=%s order_id=%s",
                store_id, order_id,
            )
            return jsonify({
                "success": False, "ok": False, "governed": True,
                "reason": "exact_amazon_promise_recovery_exception", "error": str(exc)[:500],
                "store_id": store_id, "order_id": order_id, "exact_order_only": True,
                "db_check_completed": True, "gaps_before": sorted(gaps),
                "calls_started": calls_started, "marketplace_write_started": False,
            }), 502

    if gaps & label_gaps:
        calls_started.append("amazon_purchased_label")
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

    # Provider return values are never the final truth. Expire the session, read the
    # canonical DB again, and re-run Data Truth. Only persisted changes count.
    db.session.expire_all()
    after = _database_readback(store_id, order_id)
    after_review = review_fbm_data_truth(
        store_id=store_id, order_id=order_id, platform="amazon", readback=after,
    )
    gaps_after = set(after_review.get("missing") or []) | set(after_review.get("unverified") or [])
    persisted_recovered = sorted(gaps - gaps_after)

    hydration = dict(tracking_result)
    hydration["promise_readback"] = promise_readback
    hydration["shipping_label"] = shipping_label
    return jsonify({
        "success": True, "ok": True, "governed": True, "fulfillment_type": "FBM",
        "exact_order_only": True, "broad_scan_started": False, "order_replayed": False,
        "stock_mutation_started": False, "marketplace_write_started": False,
        "store_id": store_id, "order_id": order_id,
        "db_check_completed": True, "db_authority": True,
        "gaps_before": sorted(gaps), "calls_started": calls_started,
        "calls_made": len(calls_started), "persisted_recovered": persisted_recovered,
        "gaps_after": sorted(gaps_after), "truth_review_after": after_review,
        "hydration": hydration,
        "shipping_cost_recovery": {
            "attempted": "amazon_purchased_label" in calls_started,
            "source": "existing_amazon_purchased_label_readback",
            "shipping_cost_persisted": bool(shipping_label.get("shipping_cost_persisted")),
            "shipping_cost": shipping_label.get("shipping_cost"),
            "shipping_cost_currency": shipping_label.get("shipping_cost_currency"),
        },
        "database_readback": after,
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
