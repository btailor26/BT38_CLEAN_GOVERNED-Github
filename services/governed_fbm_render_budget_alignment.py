"""Keep the existing FBM browser-session snapshot inside a first-render budget.

This does not create another FBM read path. The existing governed global-search
snapshot remains the sole session dataset and retains its 300-row ceiling,
canonical order selection, request caches, local search, tabs and health. Only
its discovery multiplier is tightened so opening /fbm cannot hydrate up to
1,201 MarketplaceOrder candidates before returning HTML.

No marketplace/provider call, polling loop, write path or background worker is
introduced here.
"""
from __future__ import annotations


def install_governed_fbm_render_budget_alignment(app) -> None:
    if getattr(app, "_bt38_fbm_render_budget_alignment_installed", False):
        return

    from services import governed_fbm_global_search_alignment as session_alignment

    # The canonical snapshot already has a 300-row hard ceiling. A 4x candidate
    # multiplier made an ordinary page open hydrate as many as 1,201 ORM rows
    # before render. Keep the same authority and canonical selector, but cap the
    # discovery query at 301 candidates (300 + the existing truncation sentinel).
    session_alignment._SESSION_CANDIDATE_MULTIPLIER = 1

    app._bt38_fbm_render_budget_alignment_installed = True
    app.logger.info(
        "BT38 FBM render budget aligned: existing session snapshot capped at 301 candidates; no marketplace/provider page reads"
    )
