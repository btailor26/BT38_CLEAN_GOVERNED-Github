"""Keep FBM presentation controls on the existing browser working set.

This module changes presentation only. It does not query or write the DB and does
not call a marketplace/provider. The existing FBM event/session controller owns
History, lifecycle and search changes after the initial rendered set. Existing
FBM pagination remains the only page-size/paging authority.
"""
from __future__ import annotations

from flask import request


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
        '<div id="bt38FbmControls" class="d-flex gap-2 align-items-center flex-wrap">'
        '<label class="small text-muted mb-0">History</label>'
        f'<select id="bt38FbmRange" class="form-select form-select-sm" style="width:auto" aria-label="FBM history">{options}</select>'
        '<input id="bt38FbmFrom" class="form-control form-control-sm" style="width:auto;display:none" type="date" aria-label="From date">'
        '<input id="bt38FbmTo" class="form-control form-control-sm" style="width:auto;display:none" type="date" aria-label="To date">'
        '<input id="bt38FbmGlobalSearchInput" class="form-control form-control-sm" style="width:min(300px,65vw)" type="search" autocomplete="off" placeholder="Order, SKU, tracking, carrier or status">'
        '<button id="bt38FbmGlobalSearchClear" class="btn btn-sm btn-outline-secondary" type="button">Clear search</button>'
        '</div>'
        '</div>'
    )


def install_governed_fbm_local_controls_alignment(app) -> None:
    if getattr(app, "_bt38_fbm_local_controls_alignment_installed", False):
        return
    @app.after_request
    def bt38_fbm_local_controls_response(response):
        path = request.path.rstrip("/") or "/"
        if path != "/fbm" or response.status_code != 200 or not response.content_type or "text/html" not in response.content_type:
            return response
        html = response.get_data(as_text=True)
        if 'id="bt38FbmControls"' in html:
            return response
        marker = '<div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2"><div><span class="fw-semibold">FBM Orders</span>'
        index = html.find(marker)
        if index < 0:
            return response
        card_start = html.rfind('<div class="card">', 0, index + 1)
        if card_start < 0:
            return response
        html = html[:card_start] + '<div class="card">\n' + _local_controls_html() + html[card_start + len('<div class="card">'):]
        response.set_data(html)
        return response
    app._bt38_fbm_local_controls_alignment_installed = True
    app.logger.info(
        "BT38 FBM controls aligned: one explicit local renderer; History/lifecycle/search are browser-local; existing pagination retained; default History=3d; no filter GET/navigation"
    )
