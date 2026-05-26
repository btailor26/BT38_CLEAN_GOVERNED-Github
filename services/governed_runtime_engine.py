"""
BT38 GOVERNED RUNTIME ENGINE

One governed automation starter:
- Full sync cadence: 8 hours
- Light reconcile cadence: 15 minutes
- FBA import stays read-only
- Marketplace push remains controlled by existing fuse/store settings
- Webhook/group notifications may trigger immediate governed group refresh later
- No legacy direct marketplace execution is started here
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta

_started = False
_started_at = None
_status_lock = threading.Lock()
_last_full_sync = None
_last_light_reconcile = None
_last_fba_import = None
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

def _stores_for_fba_import():
    from models import Store
    return (
        Store.query
        .filter(Store.is_active == True)  # noqa: E712
        .filter(Store.platform.ilike("%amazon%"))
        .filter(Store.fba_import_enabled == True)  # noqa: E712
        .all()
    )

def _run_fba_read_only_import_cycle():
    global _last_fba_import

    if not _config_on("import_enabled", True):
        _safe_log("FBA import skipped: import_enabled OFF")
        return
    if not _config_on("runtime_import_enabled", True):
        _safe_log("FBA import skipped: runtime_import_enabled OFF")
        return
    if not _config_on("marketplace_import_enabled", True):
        _safe_log("FBA import skipped: marketplace_import_enabled OFF")
        return

    from services.governed_amazon_inventory_import import run_governed_amazon_inventory_import

    stores = _stores_for_fba_import()
    for store in stores:
        try:
            result = run_governed_amazon_inventory_import(store_id=store.id)
            _safe_log(f"FBA read-only import complete store_id={store.id} result={result}")
        except Exception as exc:
            _safe_error(f"FBA read-only import failed store_id={getattr(store, 'id', None)}", exc)

    _last_fba_import = datetime.utcnow()

def _run_light_reconcile_cycle():
    global _last_light_reconcile

    # Phase 1: FBA/order/webhook light cycle.
    # This intentionally avoids blind full Sync All.
    _run_fba_read_only_import_cycle()
    _last_light_reconcile = datetime.utcnow()
    _safe_log("15-minute light reconcile complete")

def _run_full_sync_cycle():
    global _last_full_sync

    # Phase 1 full cycle: run safe read-only/import side first.
    # Marketplace push remains controlled by existing manual/governed paths and store fuses.
    _run_fba_read_only_import_cycle()
    _last_full_sync = datetime.utcnow()
    _safe_log("8-hour full sync cycle complete")

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

                if _last_full_sync is None or (now - _last_full_sync).total_seconds() >= FULL_SYNC_SECONDS:
                    if _config_on("sync_enabled", False) and _config_on("sync_worker_enabled", False):
                        _run_full_sync_cycle()

        except Exception as exc:
            _safe_error("Engine loop error", exc)

        time.sleep(30)

def start_governed_runtime_engine(app):
    """
    Starts the governed runtime engine once per process.

    This does not bypass fuse settings.
    This does not create a new marketplace execution authority.
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
        # Existing queue consumer is callable and governed-audited.
        # If it fails, the engine still keeps FBA/read-only reconcile alive.
        try:
            from sync_dispatcher import start_dispatcher
            start_dispatcher()
            _safe_log("Governed dispatcher starter called")
        except Exception as exc:
            _safe_error("Dispatcher starter failed", exc)

        thread = threading.Thread(target=_engine_loop, args=(app,), daemon=True, name="BT38GovernedRuntimeEngine")
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
        "last_fba_import": _last_fba_import.isoformat() if _last_fba_import else None,
        "next_full_sync_seconds": max(0, FULL_SYNC_SECONDS - int((now - _last_full_sync).total_seconds())) if _last_full_sync else 0,
        "next_light_reconcile_seconds": max(0, LIGHT_RECONCILE_SECONDS - int((now - _last_light_reconcile).total_seconds())) if _last_light_reconcile else 0,
        "last_error": _last_error,
    }
