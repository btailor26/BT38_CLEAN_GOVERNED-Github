"""Retired legacy Bell projection alignment.

Bell presentation is owned only by governed_fbm_bell_display_only_alignment.
This module remains as an installer compatibility name while older import order
is retired; it must not patch exact-record scope, own browser storage, replace
the notification endpoint, inject scripts, read the database, or call providers.
"""
from __future__ import annotations


def install_governed_bell_event_projection_alignment(app) -> None:
    """Retired: the Bell has one display-only FBM projection owner."""
    app.logger.info("BT38 retired legacy exact-event Bell projection alignment")
