"""
BT38 GOVERNED RUNTIME ENGINE

One governed automation starter:
- Light reconcile cadence: 15 minutes
- Full refresh cadence: 8 hours
- Import/hydration runs before sync/push decisions
- Amazon FBA remains read-only
- eBay variations are imported into DB as searchable marketplace rows
- Webhooks may trigger import refresh only
- No webhook or automation path pushes directly
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime

_started = False
_started_at = None
_status_lock = threading.Lock()

_last_full_sync = None
_last_light_reconcile = None
_last_marketplace_import = None
_last_fba_import = None
_last_ebay_import = None
_last_error = None

FULL_SYNC_SECONDS = 8 * 60 * 60
LIGHT_RECONCILE_SECONDS = 15 * 60


def _truthy(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _config_on(key: str, default: bool = False) -> bool:
    try:
        from models import SystemConfig

        row = SystemConfig.query.filter_by(key=key).first()
        if not row:
            return default
        return _truthy(row.value, default)
    except Exception:
        return default


def _safe_log(message: str):
    logging.info("[GOVERNED_RUNTIME_ENGINE] %s", message)


def _safe_error(message: str, exc: Exception):
    global _last_error
    _last_error = f"{message}: {exc}"
    logging.exception("[GOVERNED_RUNTIME_ENGINE] %s", _last_error)


def _import_fuses_on() -> bool:
    if not _config_on("import_enabled", True):
        _safe_log("marketplace import skipped: import_enabled OFF")
        return False
    if not _config_on("runtime_import_enabled", True):
        _safe_log("marketplace import skipped: runtime_import_enabled OFF")
        return False
    if not _config_on("marketplace_import_enabled", True):
        _safe_log("marketplace import skipped: marketplace_import_enabled OFF")
        return False
    return True


def _stores_for_marketplace_import():
    from models import Store

    return (
        Store.query
        .filter(Store.is_active == True)  # noqa: E712
        .filter(Store.store_mode == "live")
        .order_by(Store.id)
        .all()
    )


def run_governed_marketplace_import_refresh(store_id=None, source="governed_runtime_engine"):
    """
    Import/hydrate marketplace data into DB only.

    This function never pushes marketplace quantities.
    Marketplace-specific rules decide what can be imported:
    - Amazon FBA/AFN: read-only inventory import
    - eBay: listing + variation child import into MarketplaceListing
    """
    global _last_marketplace_import, _last_fba_import, _last_ebay_import

    if not _import_fuses_on():
        return {
            "success": False,
            "governed": True,
            "source": source,
            "reason": "import_fuses_blocked",
            "results": [],
        }

    results = []
    stores = _stores_for_marketplace_import()

    if store_id:
        stores = [s for s in stores if int(s.id) == int(store_id)]

    for store in stores:
        platform = str(store.platform or "").strip().lower()

        try:
            if "amazon" in platform:
                if not bool(getattr(store, "fba_import_enabled", False)):
                    results.append({
                        "store_id": store.id,
                        "store": store.name,
                        "platform": store.platform,
                        "skipped": True,
                        "reason": "fba_import_disabled",
                    })
                    continue

                from services.governed_amazon_inventory_import import run_governed_amazon_inventory_import

                result = run_governed_amazon_inventory_import(store_id=store.id)
                _last_fba_import = datetime.utcnow()

                results.append({
                    "store_id": store.id,
                    "store": store.name,
                    "platform": store.platform,
                    "import_type": "amazon_fba_read_only",
                    "success": True,
                    "result": result,
                })
                continue

            if "ebay" in platform:
                from services.governed_ebay_inventory_import import run_governed_ebay_inventory_import

                result = run_governed_ebay_inventory_import(store_id=store.id)
                _last_ebay_import = datetime.utcnow()

                results.append({
                    "store_id": store.id,
                    "store": store.name,
                    "platform": store.platform,
                    "import_type": "ebay_variation_hydration",
                    "success": True,
                    "result": result,
                })
                continue

            results.append({
                "store_id": store.id,
                "store": store.name,
                "platform": store.platform,
                "skipped": True,
                "reason": "unsupported_marketplace_import",
            })

        except Exception as exc:
            _safe_error(f"marketplace import failed store_id={getattr(store, 'id', None)}", exc)
            results.append({
                "store_id": getattr(store, "id", None),
                "store": getattr(store, "name", None),
                "platform": getattr(store, "platform", None),
                "success": False,
                "error": str(exc),
            })

    _last_marketplace_import = datetime.utcnow()

    return {
        "success": True,
        "governed": True,
        "source": source,
        "import_only": True,
        "push_started": False,
        "sync_started": False,
        "results": results,
    }


def _run_light_reconcile_cycle():
    global _last_light_reconcile

    run_governed_marketplace_import_refresh(source="light_reconcile_15m")
    _last_light_reconcile = datetime.utcnow()
    _safe_log("15-minute light reconcile import refresh complete")


def _run_full_sync_cycle():
    global _last_full_sync

    run_governed_marketplace_import_refresh(source="full_sync_8h_import_first")
    _last_full_sync = datetime.utcnow()
    _safe_log("8-hour full cycle import refresh complete")


def _engine_loop(app):
    global _last_full_sync, _last_light_reconcile

    _safe_log("Engine loop started")

    while True:
        try:
            with app.app_context():
                if _config_on("read_only_mode", False):
                    _safe_log("Runtime paused: read_only_mode ON")
                    time.sleep(60)
                    continue

                now = datetime.utcnow()

                if _last_light_reconcile is None or (now - _last_light_reconcile).total_seconds() >= LIGHT_RECONCILE_SECONDS:
                    if _config_on("scheduler_enabled", False) and _config_on("reconcile_15m_enabled", False):
                        _run_light_reconcile_cycle()
                    else:
                        _safe_log("15-minute reconcile skipped by fuse box")
                        _last_light_reconcile = now

                if _last_full_sync is None or (now - _last_full_sync).total_seconds() >= FULL_SYNC_SECONDS:
                    if _config_on("sync_enabled", False) and _config_on("sync_worker_enabled", False):
                        _run_full_sync_cycle()
                    else:
                        _safe_log("8-hour full cycle skipped by fuse box")
                        _last_full_sync = now

        except Exception as exc:
            _safe_error("Engine loop error", exc)

        time.sleep(30)


def start_governed_runtime_engine(app):
    """
    Starts the governed runtime engine once per process.

    This does not bypass fuse settings.
    This does not create a second marketplace authority.
    """
    global _started, _started_at

    with _status_lock:
        if _started:
            return False

        enabled = _truthy(os.getenv("ENABLE_GOVERNED_RUNTIME_ENGINE", "true"), True)
        if not enabled:
            _safe_log("ENABLE_GOVERNED_RUNTIME_ENGINE is OFF")
            return False

        _started = True
        _started_at = datetime.utcnow()

    try:
        try:
            from sync_dispatcher import start_dispatcher
            start_dispatcher()
            _safe_log("Governed dispatcher starter called")
        except Exception as exc:
            _safe_error("Dispatcher starter failed", exc)

        thread = threading.Thread(
            target=_engine_loop,
            args=(app,),
            daemon=True,
            name="BT38GovernedRuntimeEngine",
        )
        thread.start()
        _safe_log("Governed runtime engine started")
        return True
    except Exception as exc:
        _safe_error("Governed runtime engine failed to start", exc)
        return False


def get_governed_runtime_status():
    now = datetime.utcnow()
    return {
        "engine_started": bool(_started),
        "runtime_mode": "AUTOMATED GOVERNED" if _started else "MANUAL GOVERNED",
        "execution_mode": "AUTOMATED + MANUAL GOVERNED" if _started else "MANUAL ONLY",
        "workers_running": bool(_started),
        "schedulers_running": bool(_started),
        "queue_consumers_running": bool(_started),
        "started_at": _started_at.isoformat() if _started_at else None,
        "last_full_sync": _last_full_sync.isoformat() if _last_full_sync else None,
        "last_light_reconcile": _last_light_reconcile.isoformat() if _last_light_reconcile else None,
        "last_marketplace_import": _last_marketplace_import.isoformat() if _last_marketplace_import else None,
        "last_fba_import": _last_fba_import.isoformat() if _last_fba_import else None,
        "last_ebay_import": _last_ebay_import.isoformat() if _last_ebay_import else None,
        "next_full_sync_seconds": max(0, FULL_SYNC_SECONDS - int((now - _last_full_sync).total_seconds())) if _last_full_sync else 0,
        "next_light_reconcile_seconds": max(0, LIGHT_RECONCILE_SECONDS - int((now - _last_light_reconcile).total_seconds())) if _last_light_reconcile else 0,
        "last_error": _last_error,
    }
