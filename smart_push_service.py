"""
BT38 smart push service disabled.

Temporary fail-closed compatibility shell for shutdown phase.
All marketplace push orchestration, classification, FBM push logic,
and direct listing execution are disabled.
"""

import logging

SMART_PUSH_DISABLED = True
LEGACY_PUSH_ORCHESTRATION_DISABLED = True


class SmartPushService:
    execution_disabled = True

    def __init__(self):
        logging.warning("[SMART_PUSH_DISABLED] SmartPushService initialized in disabled mode.")

    def classify_listing(self, listing):
        return "disabled"

    def update_listing_classification(self, listing):
        return False

    def get_pushable_listings(self, store_id=None):
        return []

    def push_single_listing(self, listing, store):
        return False, "Smart push disabled"

    def push_to_store(self, store):
        return {
            "success": False,
            "execution_blocked": True,
            "smart_push_disabled": True,
            "processed": 0,
            "successful": 0,
            "failed": 0,
            "errors": ["Legacy smart push disabled"],
        }

    def push_specific_sku(self, sku: str, store_name: str = None):
        return {
            "success": False,
            "execution_blocked": True,
            "smart_push_disabled": True,
            "sku": sku,
            "errors": ["Legacy smart push disabled"],
        }


smart_push_service = SmartPushService()
