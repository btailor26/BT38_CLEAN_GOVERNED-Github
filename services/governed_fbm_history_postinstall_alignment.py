"""Enforce final FBM history-control authority after legacy installer chaining."""
from __future__ import annotations

from services import governed_fbm_all_orders_health_alignment as health_alignment
from services import governed_fbm_page_alignment as page


_original_install = health_alignment.install_governed_fbm_all_orders_health_alignment


def _aligned_install(app) -> None:
    _original_install(app)
    # all-orders health owns metrics, not a second controls/search surface.
    page._period_controls = lambda _health: ""
    app.logger.info("BT38 FBM controls finalised: one history/search surface; health header controls retired")


health_alignment.install_governed_fbm_all_orders_health_alignment = _aligned_install
