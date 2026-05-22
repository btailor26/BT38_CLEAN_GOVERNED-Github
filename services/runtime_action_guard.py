"""BT38 runtime fuse-box guard.

Single rule:
If the settings cockpit / DB switch is OFF, the action must not run.

Authority order:
1. Emergency/read-only/queue fuse from SystemConfig
2. Action fuse from SystemConfig
3. Store active/mode/settings
4. Credential/read-only marketplace checks

This module never calls marketplace APIs, never enqueues jobs, and never mutates
inventory/listing/store state. It only decides allowed/blocked with reasons.
"""

import logging
import os
from typing import Any, Dict, Optional

READ_ONLY_ACTIONS = {"preview", "read", "read_only", "status", "audit"}
RUNTIME_ACTIONS = {"push", "sync", "import"}
VALID_ACTIONS = READ_ONLY_ACTIONS | RUNTIME_ACTIONS


def _store_value(store: Any, attr: str, default: Any = None) -> Any:
    return getattr(store, attr, default) if store is not None else default


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value is True
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "on", "enabled", "live"}


def _falsey(value: Any) -> bool:
    if isinstance(value, bool):
        return value is False
    text = str(value).strip().lower()
    return text in {"0", "false", "no", "off", "disabled", "none", ""}


def _structured_result(store: Any, action_type: str, manual: bool, allowed: bool, reason: str) -> Dict[str, Any]:
    return {
        "allowed": allowed,
        "reason": reason,
        "action_type": action_type,
        "manual": bool(manual),
        "store_id": _store_value(store, "id"),
        "store_name": _store_value(store, "name"),
        "fuse_box_checked": True,
        "source": "SystemConfig+Store",
    }


def _config_value(key: str, default: Any = None) -> Any:
    try:
        from models import SystemConfig

        row = SystemConfig.query.filter_by(key=key).first()
        if row is None:
            return default
        return row.value
    except Exception as exc:
        logging.debug("Runtime fuse skipped SystemConfig lookup for %s: %s", key, exc)
        return default


def _config_on(key: str, default: bool = False) -> bool:
    return _truthy(_config_value(key, "true" if default else "false"))


def _config_off(key: str, default: bool = False) -> bool:
    return _falsey(_config_value(key, "false" if default else "true"))


def _store_flag_disabled(store: Any, attr: str) -> bool:
    if store is None or not hasattr(store, attr):
        return False
    return _falsey(getattr(store, attr))


def _global_env_block(action_type: str) -> Optional[str]:
    """Environment can still hard-stop dangerous execution.

    Env must only be an outer circuit breaker, not the normal operator control.
    Normal owner control comes from SystemConfig settings cockpit.
    """
    execution_mode = os.getenv("EXECUTION_MODE", "").strip().lower()
    if execution_mode in {"read-only", "readonly", "disabled"} and action_type in RUNTIME_ACTIONS:
        return f"ENV EXECUTION_MODE={execution_mode} blocks {action_type}"

    if action_type == "push" and os.getenv("PUSH_ENABLED", "true").strip().lower() in {"0", "false", "no", "off"}:
        return "ENV PUSH_ENABLED blocks push"

    return None


def _system_fuse_block(action_type: str, manual: bool) -> Optional[str]:
    """Main DB-backed fuse box.

    If any relevant fuse is OFF/ON-blocking, action must stop here.
    """
    if action_type not in RUNTIME_ACTIONS:
        return None

    if _config_on("read_only_mode", default=False):
        return "Settings fuse read_only_mode is ON"

    if _config_on("queue_frozen", default=False) and not manual:
        return "Settings fuse queue_frozen is ON"

    if action_type == "push":
        required = [
            "push_enabled",
            "runtime_push_enabled",
            "marketplace_push_enabled",
        ]
        if manual:
            required.append("manual_push_enabled")

        for key in required:
            if not _config_on(key, default=False):
                return f"Settings fuse {key} is OFF"

    if action_type == "import":
        required = [
            "import_enabled",
            "runtime_import_enabled",
            "marketplace_import_enabled",
        ]
        if manual:
            required.append("manual_import_enabled")

        for key in required:
            if not _config_on(key, default=False):
                return f"Settings fuse {key} is OFF"

    if action_type == "sync":
        required = [
            "sync_enabled",
            "runtime_sync_enabled",
            "marketplace_sync_enabled",
        ]
        if manual:
            required.append("manual_sync_enabled")

        for key in required:
            if not _config_on(key, default=False):
                return f"Settings fuse {key} is OFF"

    return None


def is_runtime_action_allowed(store, action_type, manual=False, context=None):
    """Return a structured authorization decision for runtime actions.

    This is the only normal runtime decision point for push/sync/import.
    Every governed execution path should call this before marketplace execution.
    """
    normalized_action = (action_type or "").strip().lower()
    manual = bool(manual)
    context = context or {}

    if normalized_action not in VALID_ACTIONS:
        return _structured_result(store, normalized_action, manual, False, "Unknown or unsupported runtime action type")

    if normalized_action in READ_ONLY_ACTIONS:
        return _structured_result(store, normalized_action, manual, True, "Read-only runtime action allowed")

    env_block = _global_env_block(normalized_action)
    if env_block:
        return _structured_result(store, normalized_action, manual, False, env_block)

    fuse_block = _system_fuse_block(normalized_action, manual)
    if fuse_block:
        return _structured_result(store, normalized_action, manual, False, fuse_block)

    if store is None:
        return _structured_result(store, normalized_action, manual, False, "Store is required for runtime execution")

    if not bool(_store_value(store, "is_active", False)):
        return _structured_result(store, normalized_action, manual, False, "Store is inactive")

    store_mode = str(_store_value(store, "store_mode", "safe") or "safe").strip().lower()
    if store_mode != "live" and normalized_action in {"push", "sync", "import"}:
        return _structured_result(store, normalized_action, manual, False, f"Store fuse store_mode={store_mode} blocks {normalized_action}")

    if normalized_action == "push":
        if any(_store_flag_disabled(store, attr) for attr in ("push_enabled", "auto_push_enabled", "marketplace_push_enabled")):
            return _structured_result(store, normalized_action, manual, False, "Store fuse disables push execution")

    if normalized_action == "sync":
        if any(_store_flag_disabled(store, attr) for attr in ("sync_enabled", "auto_sync_enabled", "marketplace_sync_enabled", "fbm_sync_enabled")):
            return _structured_result(store, normalized_action, manual, False, "Store fuse disables sync execution")

    if normalized_action == "import":
        if any(_store_flag_disabled(store, attr) for attr in ("import_enabled", "fba_import_enabled", "marketplace_import_enabled")):
            return _structured_result(store, normalized_action, manual, False, "Store fuse disables import execution")

    if normalized_action in RUNTIME_ACTIONS and not _store_value(store, "api_key"):
        return _structured_result(store, normalized_action, manual, False, "Store credentials are missing")

    platform = str(_store_value(store, "platform", "") or "").strip().lower()
    fulfillment_type = str(_store_value(store, "fulfillment_type", "") or "").strip().upper()
    if normalized_action == "push" and ("fba" in platform or fulfillment_type == "FBA"):
        return _structured_result(store, normalized_action, manual, False, "Amazon FBA/read-only stores cannot push")

    return _structured_result(store, normalized_action, manual, True, "Runtime fuse box allowed action")
