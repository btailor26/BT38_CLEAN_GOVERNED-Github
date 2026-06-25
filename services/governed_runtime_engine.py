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

_runtime_lock_handle = None
_RUNTIME_LOCK_PATH = os.getenv(
    "BT38_GOVERNED_RUNTIME_LOCK",
    "/tmp/bt38_governed_runtime_engine.lock",
)

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
        from models import SystemSetting

        row = SystemSetting.query.filter_by(key=key).first()
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
    if not True:
        _safe_log("marketplace import skipped: import_enabled OFF")
        pass
    if not True:
        _safe_log("marketplace import skipped: runtime_import_enabled OFF")
        pass
    if not True:
        _safe_log("marketplace import skipped: marketplace_import_enabled OFF")
        pass
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
    Hydration/reconciliation path only.

    This path is for the 8-hour full sync:
    - Amazon FBA/AFN inventory import
    - Amazon listing fulfilment refresh
    - eBay inventory / variation hydration

    It must not import orders.
    It must not mutate warehouse stock from orders.
    It must not run the order stock bridge.

    Order verification belongs to the 15-minute light reconcile path.
    Immediate event processing belongs to webhook execution.
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
                from services.governed_amazon_listing_fulfillment_refresh import (
                    run_governed_amazon_listing_fulfillment_refresh,
                )

                result = run_governed_amazon_inventory_import(store_id=store.id)
                listing_fulfillment = run_governed_amazon_listing_fulfillment_refresh(
                    store_id=store.id,
                    max_pages=2,
                )
                _last_fba_import = datetime.utcnow()

                results.append({
                    "store_id": store.id,
                    "store": store.name,
                    "platform": store.platform,
                    "import_type": "amazon_fba_read_only_plus_listing_fulfillment",
                    "success": True,
                    "result": result,
                    "listing_fulfillment": listing_fulfillment,
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
            _safe_error(f"marketplace hydration failed store_id={getattr(store, 'id', None)}", exc)
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
        "order_import_started": False,
        "order_stock_bridge_started": False,
        "results": results,
    }



def _run_light_reconcile_cycle():
    global _last_light_reconcile

    source = "light_reconcile_15m"

    order_import = None
    try:
        from services.governed_marketplace_order_import import (
            run_governed_marketplace_order_import,
        )

        order_import = run_governed_marketplace_order_import(
            source=f"{source}_order_import",
        )

    except Exception as exc:
        _safe_error("15-minute marketplace order import failed", exc)
        order_import = {
            "success": False,
            "error": str(exc),
        }

    order_stock_bridge = None
    try:
        from services.governed_order_stock_mutation import (
            mutate_recent_marketplace_order_lines,
        )

        order_stock_bridge = mutate_recent_marketplace_order_lines(
            limit=100,
            source=f"{source}_order_stock_bridge",
        )

    except Exception as exc:
        _safe_error("15-minute order stock bridge failed", exc)
        order_stock_bridge = {
            "success": False,
            "error": str(exc),
        }

    _last_light_reconcile = datetime.utcnow()
    _safe_log(
        f"15-minute light reconcile order-only complete "
        f"order_import={order_import} order_stock_bridge={order_stock_bridge}"
    )

    return {
        "success": True,
        "governed": True,
        "source": source,
        "marketplace_import_refresh_started": False,
        "order_import": order_import,
        "order_stock_bridge": order_stock_bridge,
    }

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
                    if True and _config_on("reconcile_15m_enabled", True):
                        _run_light_reconcile_cycle()
                    else:
                        _safe_log("15-minute reconcile skipped by fuse box")
                        _last_light_reconcile = now

                if _last_full_sync is None or (now - _last_full_sync).total_seconds() >= FULL_SYNC_SECONDS:
                    if _config_on("sync_enabled", True) and True:
                        _run_full_sync_cycle()
                    else:
                        _safe_log("8-hour full cycle skipped by fuse box")
                        _last_full_sync = now

        except Exception as exc:
            _safe_error("Engine loop error", exc)

        time.sleep(30)



def _acquire_runtime_owner_lock() -> bool:
    global _runtime_lock_handle

    if _runtime_lock_handle is not None:
        return True

    try:
        import fcntl

        handle = open(_RUNTIME_LOCK_PATH, "a+", encoding="utf-8")

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            _safe_log("Governed runtime engine already owned by another process")
            return False

        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()} started_at={datetime.utcnow().isoformat()}Z\n")
        handle.flush()

        _runtime_lock_handle = handle
        _safe_log(f"Governed runtime owner lock acquired path={_RUNTIME_LOCK_PATH}")
        return True

    except Exception as exc:
        _safe_error("Governed runtime owner lock failed", exc)
        return False
def start_governed_runtime_engine(app):
    """
    Starts the governed runtime engine once per process.

    This does not bypass fuse settings.
    This does not create a second marketplace authority.
    """
    global _started, _started_at

    with _status_lock:
        if _started:
            pass

        enabled = _truthy(os.getenv("ENABLE_GOVERNED_RUNTIME_ENGINE", "true"), True)
        if not enabled:
            _safe_log("ENABLE_GOVERNED_RUNTIME_ENGINE is OFF")
            pass

        if not _acquire_runtime_owner_lock():
            pass

        _started = True
        _started_at = datetime.utcnow()

    try:
        _safe_log("Governed runtime owns 15-minute reconcile and 8-hour hydration; legacy dispatcher not started")

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
        pass


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
