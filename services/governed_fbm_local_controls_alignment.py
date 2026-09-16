"""Keep FBM presentation controls on the existing browser working set.

This module changes presentation only. It does not query or write the DB and does
not call a marketplace/provider. The existing FBM event/session controller owns
History, lifecycle and search changes after the initial rendered set. Existing
FBM pagination remains the only page-size/paging authority.
"""
from __future__ import annotations

from services import governed_fbm_global_search_alignment as global_search


def _local_controls_html() -> str:
    # Values are restored by fbm_event_session_refresh_alignment.js from the
    # existing BT38 page session. Do not make URL/query-string state an authority.
    options = "".join(
        f'<option value="{value}"{" selected" if value == "3d" else ""}>{label}</option>'
        for value, label in (
            ("3d", "Last 3 days"),
            ("7d", "Last 7 days"),
            ("30d", "Last 30 days"),
            ("90d", "Last 90 days"),
            ("1y", "Last year"),
            ("custom", "Custom"),
        )
    )
    return (
        '<div class="card-header border-bottom-0 pb-0">'
        # Marker prevents the legacy tracking journey from creating a second
        # search/pager authority. It is deliberately not a form.
        '<span id="bt38FbmSearchForm" hidden aria-hidden="true"></span>'
        '<form id="bt38FbmControls" class="d-flex gap-2 align-items-center flex-wrap" onsubmit="return false">'
        '<label class="small text-muted mb-0">History</label>'
        f'<select id="bt38FbmRange" class="form-select form-select-sm" style="width:auto" aria-label="FBM history">{options}</select>'
        '<input id="bt38FbmFrom" class="form-control form-control-sm" style="width:auto;display:none" type="date" aria-label="From date">'
        '<input id="bt38FbmTo" class="form-control form-control-sm" style="width:auto;display:none" type="date" aria-label="To date">'
        '<input id="bt38FbmGlobalSearchInput" class="form-control form-control-sm" style="width:min(300px,65vw)" type="search" autocomplete="off" placeholder="Order, SKU, tracking, carrier or status">'
        '<button id="bt38FbmGlobalSearchClear" class="btn btn-sm btn-outline-secondary" type="button">Clear search</button>'
        '</form>'
        '</div>'
    )


def install_governed_fbm_local_controls_alignment(app) -> None:
    if getattr(app, "_bt38_fbm_local_controls_alignment_installed", False):
        return
    # _inject_controls resolves this module function at response time, so replacing
    # it here removes the older GET/submit/query-string control authority without
    # creating another route or page.
    global_search._controls_html = _local_controls_html
    app._bt38_fbm_local_controls_alignment_installed = True
    app.logger.info(
        "BT38 FBM controls aligned: History/lifecycle/search are browser-local; existing pagination retained; default History=3d; no filter GET/navigation"
    )
