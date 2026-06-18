"""BT38 governed warehouse sync execution.

Rules:
- Fuse box remains the authority.
- UI buttons are shortcuts only.
- No legacy queue workers are revived.
- No old push_stock routes are used.
- All-store warehouse sync must discover stores first, then pass each store into
  the fuse box. It must never ask the fuse box to approve sync with store=None.
- Operator results must show proof, not a vague success/failure alert.
"""

from __future__ import annotations

from datetime import datetime

from app import db
from models import MarketplaceListing, Store, SystemLog
from services.runtime_action_guard import is_runtime_action_allowed


READ_ONLY_MARKERS = (
    "fba/afn is read-only",
    "no fba push path",
    "fba push path is permitted",
)
AUTH_MARKERS = (
    "invalid access token",
    "oauth",
    "unauthorized",
    "401",
)


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


def _result_text(row) -> str:
    parts = [
        row.get("reason"),
        row.get("error"),
        row.get("message"),
    ]
    adapter = row.get("adapter_result") if isinstance(row, dict) else None
    if isinstance(adapter, dict):
        parts.extend([
            adapter.get("reason"),
            adapter.get("message"),
            adapter.get("response_text"),
        ])
        amazon_result = adapter.get("amazon_result")
        if isinstance(amazon_result, dict):
            parts.extend([
                amazon_result.get("reason"),
                amazon_result.get("message"),
                amazon_result.get("error"),
                amazon_result.get("response_text"),
            ])
    return " ".join(str(p) for p in parts if p).lower()


def _proof_row(row):
    adapter = row.get("adapter_result") if isinstance(row, dict) else None
    status_code = None
    response_text = None
    if isinstance(adapter, dict):
        status_code = adapter.get("status_code")
        response_text = adapter.get("response_text")
        amazon_result = adapter.get("amazon_result")
        if isinstance(amazon_result, dict):
            status_code = status_code or amazon_result.get("status_code")
            response_text = response_text or amazon_result.get("response_text") or amazon_result.get("message") or amazon_result.get("error")
    return {
        "listing_id": row.get("listing_id"),
        "sku": row.get("sku"),
        "store_id": row.get("store_id"),
        "platform": row.get("platform"),
        "ok": bool(row.get("ok") or row.get("success")),
        "reason": row.get("reason") or row.get("error") or row.get("message") or "No reason returned.",
        "status_code": status_code,
        "response_text": (str(response_text)[:500] if response_text else None),
    }


def _summarize_results(results):
    pushed = 0
    blocked = 0
    skipped_read_only = 0
    auth_failed = 0
    failed = 0
    failure_samples = []
    skipped_samples = []

    for row in results:
        if row.get("ok") or row.get("success"):
            pushed += 1
            continue

        text = _result_text(row)
        if row.get("execution_blocked"):
            blocked += 1
        if any(marker in text for marker in READ_ONLY_MARKERS):
            skipped_read_only += 1
            if len(skipped_samples) < 20:
                skipped_samples.append(_proof_row(row))
            continue
        if any(marker in text for marker in AUTH_MARKERS):
            auth_failed += 1

        failed += 1
        if len(failure_samples) < 20:
            failure_samples.append(_proof_row(row))

    return {
        "pushed": pushed,
        "blocked": blocked,
        "skipped_read_only": skipped_read_only,
        "auth_failed": auth_failed,
        "failed": failed,
        "failure_samples": failure_samples,
        "skipped_samples": skipped_samples,
    }


def _combine_store_results(store_results, actor):
    pushed = sum(int(row.get("pushed") or 0) for row in store_results)
    blocked = sum(int(row.get("blocked") or 0) for row in store_results)
    skipped_read_only = sum(int(row.get("skipped_read_only") or 0) for row in store_results)
    auth_failed = sum(int(row.get("auth_failed") or 0) for row in store_results)
    failed = sum(int(row.get("failed") or 0) for row in store_results)
    checked = sum(int(row.get("checked") or 0) for row in store_results)
    total = sum(int(row.get("total") or 0) for row in store_results)

    failure_samples = []
    skipped_samples = []
    for row in store_results:
        failure_samples.extend(row.get("failure_samples") or [])
        skipped_samples.extend(row.get("skipped_samples") or [])
    failure_samples = failure_samples[:20]
    skipped_samples = skipped_samples[:20]

    blocked_stores = [row for row in store_results if row.get("execution_blocked")]
    failed_stores = [row for row in store_results if row.get("failed", 0) > 0]

    _log_sync(
        "Governed all-store warehouse sync executed",
        (
            f"actor={actor} stores={len(store_results)} total={total} checked={checked} "
            f"pushed={pushed} skipped_read_only={skipped_read_only} auth_failed={auth_failed} "
            f"blocked={blocked} failed={failed} blocked_stores={len(blocked_stores)} "
            f"failed_stores={len(failed_stores)}"
        ),
    )

    return {
        "success": failed == 0 and auth_failed == 0,
        "ok": failed == 0 and auth_failed == 0,
        "governed": True,
        "manual": True,
        "mode": "governed_all_store_execution",
        "store_scope": "all_active_stores",
        "stores_checked": len(store_results),
        "total": total,
        "checked": checked,
        "pushed": pushed,
        "blocked": blocked,
        "skipped_read_only": skipped_read_only,
        "auth_failed": auth_failed,
        "failed": failed,
        "message": (
            f"Governed warehouse sync checked {len(store_results)} active store(s). "
            f"Pushed: {pushed}. Read-only skipped: {skipped_read_only}. "
            f"Auth failed: {auth_failed}. Other failed: {failed}."
        ),
        "failure_samples": failure_samples,
        "skipped_samples": skipped_samples,
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
                "skipped_read_only": 0,
                "auth_failed": 0,
                "failed": 0,
                "message": "No active stores found for governed warehouse sync.",
                "failure_samples": [],
                "skipped_samples": [],
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
            "skipped_read_only": 0,
            "auth_failed": 0,
            "failure_samples": [],
            "skipped_samples": [],
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
            "skipped_read_only": 0,
            "auth_failed": 0,
            "failed": 0,
            "failure_samples": [],
            "skipped_samples": [],
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
            "skipped_read_only": 0,
            "auth_failed": 0,
            "failed": 0,
            "message": "No active linked marketplace listings found for governed sync.",
            "failure_samples": [],
            "skipped_samples": [],
            "results": [],
            "guard": sync_guard,
        }

    from services.governed_push_gateway import push_execution_gateway_DISABLED as push_marketplace_listing

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
                listing_id=listing.id,
                actor=actor,
                source="governed_warehouse_sync",
                actor_user=None,
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

    summary = _summarize_results(results)

    _log_sync(
        "Governed warehouse sync executed",
        (
            f"store_id={store_id} actor={actor} total={len(results)} pushed={summary['pushed']} "
            f"skipped_read_only={summary['skipped_read_only']} auth_failed={summary['auth_failed']} "
            f"blocked={summary['blocked']} failed={summary['failed']}"
        ),
    )

    return {
        "success": summary["failed"] == 0 and summary["auth_failed"] == 0,
        "ok": summary["failed"] == 0 and summary["auth_failed"] == 0,
        "governed": True,
        "manual": True,
        "mode": "governed_execution",
        "store_id": store_id,
        "store_name": getattr(store, "name", None),
        "platform": getattr(store, "platform", None),
        "total": len(results),
        "checked": len(results),
        "pushed": summary["pushed"],
        "blocked": summary["blocked"],
        "skipped_read_only": summary["skipped_read_only"],
        "auth_failed": summary["auth_failed"],
        "failed": summary["failed"],
        "message": (
            f"Governed warehouse sync executed for store {store_id}. Pushed: {summary['pushed']}. "
            f"Read-only skipped: {summary['skipped_read_only']}. Auth failed: {summary['auth_failed']}. "
            f"Other failed: {summary['failed']}."
        ),
        "failure_samples": summary["failure_samples"],
        "skipped_samples": summary["skipped_samples"],
        "results": results,
        "guard": sync_guard,
    }
