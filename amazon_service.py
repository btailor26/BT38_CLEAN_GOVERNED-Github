"""
BT38 Amazon marketplace service disabled.

This is a temporary fail-closed compatibility shell for the worker shutdown phase.
Amazon FBA, Amazon FBM, Amazon order import, Amazon listing import, Amazon feed
updates, and every direct Amazon marketplace call are blocked here.

Reason:
- BT38 must have one clear governed execution path only.
- Marketplace services must not execute directly while old sync paths are being removed.
- New routes/executors may only be added after disabled-worker and disabled-marketplace tests pass.
"""

import logging
from typing import Any, Dict, List, Tuple

MARKETPLACE_EXECUTION_DISABLED = True
AMAZON_MARKETPLACE_DISABLED = True

MARKETPLACE_REGION = {
    "A1F83G8C2ARO7P": "EU",
    "A1PA6795UKMFR9": "EU",
    "A13V1IB3VIYZZH": "EU",
    "A1RKKUPIHCS9HS": "EU",
    "APJ6JRA9NG5V4": "EU",
    "ATVPDKIKX0DER": "NA",
    "A2EUQ1WTGCTBG2": "NA",
    "A1AM78C64UM0Y8": "NA",
}

REGION_HOST = {
    "EU": "sellingpartnerapi-eu.amazon.com",
    "NA": "sellingpartnerapi-na.amazon.com",
    "FE": "sellingpartnerapi-fe.amazon.com",
}


def resolve_region_host(marketplace_id: str):
    """Keep passive marketplace metadata lookup available without API execution."""
    region = MARKETPLACE_REGION.get(marketplace_id, "EU")
    return region, REGION_HOST.get(region, REGION_HOST["EU"])


def _disabled_response(action: str) -> Dict[str, Any]:
    return {
        "success": False,
        "ok": False,
        "execution_blocked": True,
        "marketplace_disabled": True,
        "platform": "amazon",
        "action": action,
        "error": (
            "Amazon marketplace execution is disabled. "
            "Use the new governed execution path only after shutdown tests pass."
        ),
    }


class AmazonAPIService:
    """Fail-closed Amazon compatibility service.

    The class name stays available so imports do not crash, but all marketplace
    execution is blocked. This prevents FBA/FBM Amazon code from running through
    any old route, worker, scheduler, service, or debug path.
    """

    execution_disabled = True
    marketplace_disabled = True
    platform = "amazon"

    def __init__(self, *args, **kwargs):
        self.logger = logging.getLogger(__name__)
        self.store = args[0] if args else kwargs.get("store")
        self.logger.warning(
            "[MARKETPLACE_DISABLED] AmazonAPIService initialized as disabled compatibility shell."
        )

    def _blocked_tuple(self, action: str) -> Tuple[bool, str]:
        logging.warning("[MARKETPLACE_DISABLED] Amazon action blocked: %s", action)
        return False, _disabled_response(action)["error"]

    def _blocked_dict(self, action: str) -> Dict[str, Any]:
        logging.warning("[MARKETPLACE_DISABLED] Amazon action blocked: %s", action)
        return _disabled_response(action)

    def authenticate_store(self, *args, **kwargs) -> bool:
        logging.warning("[MARKETPLACE_DISABLED] Amazon authenticate_store blocked.")
        return False

    def sync_inventory_to_amazon(self, *args, **kwargs) -> Tuple[bool, str]:
        return self._blocked_tuple("sync_inventory_to_amazon")

    def sync_fba_inventory(self, *args, **kwargs) -> Tuple[bool, str]:
        return self._blocked_tuple("sync_fba_inventory")

    def get_mfn_orders(self, *args, **kwargs) -> Dict[str, Any]:
        return self._blocked_dict("get_mfn_orders")

    def check_feeds_scope(self, *args, **kwargs) -> Dict[str, Any]:
        return self._blocked_dict("check_feeds_scope")

    def __getattr__(self, name: str):
        def blocked(*args, **kwargs):
            return self._blocked_dict(name)
        return blocked
