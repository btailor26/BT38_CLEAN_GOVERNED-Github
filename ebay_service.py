"""
BT38 eBay marketplace service disabled.

This is a temporary fail-closed compatibility shell for the worker shutdown phase.
eBay inventory push, eBay listing updates, eBay imports, eBay authentication,
and every direct eBay marketplace call are blocked here.

Reason:
- BT38 must have one clear governed execution path only.
- Marketplace services must not execute directly while old sync paths are being removed.
- New routes/executors may only be added after disabled-worker and disabled-marketplace tests pass.
"""

import logging
from typing import Any, Dict, Tuple

MARKETPLACE_EXECUTION_DISABLED = True
EBAY_MARKETPLACE_DISABLED = True


def _disabled_response(action: str) -> Dict[str, Any]:
    return {
        "success": False,
        "ok": False,
        "execution_blocked": True,
        "marketplace_disabled": True,
        "platform": "ebay",
        "action": action,
        "error": (
            "eBay marketplace execution is disabled. "
            "Use the new governed execution path only after shutdown tests pass."
        ),
    }


class eBayAPIService:
    """Fail-closed eBay compatibility service.

    The class name stays available so imports do not crash, but all marketplace
    execution is blocked. This prevents eBay code from running through any old
    route, worker, scheduler, service, or debug path.
    """

    execution_disabled = True
    marketplace_disabled = True
    platform = "ebay"

    def __init__(self, *args, **kwargs):
        self.logger = logging.getLogger(__name__)
        self.logger.warning(
            "[MARKETPLACE_DISABLED] eBayAPIService initialized as disabled compatibility shell."
        )

    def _blocked_tuple(self, action: str) -> Tuple[bool, str]:
        logging.warning("[MARKETPLACE_DISABLED] eBay action blocked: %s", action)
        return False, _disabled_response(action)["error"]

    def _blocked_dict(self, action: str) -> Dict[str, Any]:
        logging.warning("[MARKETPLACE_DISABLED] eBay action blocked: %s", action)
        return _disabled_response(action)

    def authenticate_store(self, *args, **kwargs) -> bool:
        logging.warning("[MARKETPLACE_DISABLED] eBay authenticate_store blocked.")
        return False

    def push_quantity_only(self, *args, **kwargs) -> Tuple[bool, str]:
        return self._blocked_tuple("push_quantity_only")

    def get_item(self, *args, **kwargs) -> Dict[str, Any]:
        return self._blocked_dict("get_item")

    def __getattr__(self, name: str):
        def blocked(*args, **kwargs):
            return self._blocked_dict(name)
        return blocked
