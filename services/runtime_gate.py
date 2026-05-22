"""BT38 runtime gate compatibility wrapper.

One authority:
SystemConfig + Store settings via services.runtime_action_guard.

This file exists only so older governed execution code can keep calling
runtime_gate while the settings cockpit remains the real fuse box.
"""

from dataclasses import dataclass, field
from typing import Any, Dict

from services.runtime_action_guard import is_runtime_action_allowed

APPROVED_AMAZON_FBM_PUSH_TYPE = "amazon_fbm_single_sku_inventory_push"
RUNTIME_GATE_MESSAGE = "BT38 runtime execution is controlled by the settings fuse box."


@dataclass
class RuntimeCommand:
    action: str
    payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


def _resolve_action_type(command) -> str:
    action = str(getattr(command, "action", "") or "").strip().lower()
    if "push" in action:
        return "push"
    if "import" in action:
        return "import"
    if "sync" in action:
        return "sync"
    return action


def _resolve_store(command):
    try:
        from models import Store
        payload = dict(getattr(command, "payload", {}) or {})
        store_id = payload.get("store_id") or payload.get("store") or payload.get("storeId")
        if not store_id:
            return None
        return Store.query.get(int(store_id))
    except Exception:
        return None


def _manual(command) -> bool:
    payload = dict(getattr(command, "payload", {}) or {})
    metadata = dict(getattr(command, "metadata", {}) or {})
    return bool(
        payload.get("manual")
        or payload.get("manual_trigger")
        or metadata.get("manual")
        or metadata.get("manual_trigger")
        or getattr(command, "actor", None)
    )


def decision(command):
    action_type = _resolve_action_type(command)
    store = _resolve_store(command)
    result = is_runtime_action_allowed(
        store=store,
        action_type=action_type,
        manual=_manual(command),
        context={
            "source": "runtime_gate",
            "command_action": getattr(command, "action", None),
            "marketplace": getattr(command, "marketplace", None),
        },
    )
    result.setdefault("reason", RUNTIME_GATE_MESSAGE)
    return result


def is_runtime_allowed(command=None, *_args, **_kwargs) -> bool:
    if command is None:
        return False
    return bool(decision(command).get("allowed", False))


def block_reason(command=None) -> str:
    if command is None:
        return "Runtime command missing"
    return str(decision(command).get("reason") or RUNTIME_GATE_MESSAGE)


def assert_runtime_allowed(command=None, *_args, **_kwargs):
    result = decision(command)
    if not result.get("allowed", False):
        raise RuntimeError(result.get("reason") or RUNTIME_GATE_MESSAGE)
    return result
