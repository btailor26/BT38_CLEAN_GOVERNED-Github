"""Keep ordinary FBM page loads on persisted BT38 truth only.

Historical Amazon profile hydration is owned by governed marketplace events,
recovery and explicit shipping actions. Opening /fbm must never make an Amazon
or other marketplace/provider request. This alignment intentionally leaves the
existing installer callable for compatibility while removing the former
before-request exact Amazon read that could block the FBM page.
"""
from __future__ import annotations


def _hydrate_current_missing_profiles(limit: int = 1) -> None:
    """Compatibility no-op: ordinary FBM reads never hydrate marketplaces."""
    return None


def install_governed_fbm_current_amazon_profile_alignment(app) -> None:
    """Preserve the installer contract without adding a page-time network hook."""
    if getattr(app, "_bt38_fbm_current_amazon_profile_alignment", False):
        return

    app._bt38_fbm_current_amazon_profile_alignment = True
    app.logger.info(
        "BT38 FBM page alignment: persisted-data reads only; no page-time Amazon hydration"
    )
