from typing import Dict, Any

def push_execution_gateway(push_fn, *args, **kwargs) -> Dict[str, Any]:
    """
    SINGLE ENTRY POINT FOR ALL AUTO PUSH ACTIONS
    - NO BUSINESS LOGIC HERE
    - ONLY GATE CONTROL
    """

    from runtime_action_guard import is_runtime_action_allowed

    # STEP 1: fuse box check (ONLY ON/OFF)
    allowed = is_runtime_action_allowed("push")

    if not allowed:
        return {
            "success": False,
            "ok": False,
            "blocked": True,
            "reason": "fuse_box_blocked"
        }

    # STEP 2: execute actual push
    return push_fn(*args, **kwargs)
