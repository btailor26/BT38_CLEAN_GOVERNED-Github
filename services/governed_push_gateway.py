from typing import Dict, Any

def push_execution_gateway(push_fn, *args, **kwargs) -> Dict[str, Any]:
    """
    SINGLE ENTRY POINT FOR ALL AUTO PUSH ACTIONS
    """

    from runtime_action_guard import is_runtime_action_allowed

    allowed = is_runtime_action_allowed("push")

    if not allowed:
        return {
            "success": False,
            "ok": False,
            "blocked": True,
            "reason": "fuse_box_blocked"
        }

    return push_fn(*args, **kwargs)
