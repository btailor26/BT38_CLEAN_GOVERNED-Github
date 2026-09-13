"""Final FBM presentation alignment for the existing governed FBM page.

This layer is deliberately presentation-only. It may reshape the already
rendered FBM response and browser behaviour, but it must not read the database,
call a marketplace/provider, create another notification authority, poll, or
replace the existing governed bell endpoint.

The first FBM workflow view remains Ready to dispatch. Pending stays available
as a secondary view, while fulfilment eligibility continues to come from the
existing FBM page authority.
"""
from __future__ import annotations

import re

from flask import make_response, request
from flask_login import login_required


_COMMERCIAL_LABELS = (
    (("return_fulfillment_completed", "return_closed", "returned"), "Returned"),
    (("return_requested", "return_fulfillment_initiated"), "Return requested"),
    (("refund_requested",), "Refund requested"),
    (("refunded", "refund_completed", "refund_issued"), "Refunded"),
    (("cancellation_requested", "cancel_requested"), "Cancellation requested"),
    (("cancelled", "canceled"), "Cancelled"),
    (("replacement_requested",), "Replacement requested"),
    (("replacement", "replaced"), "Replacement"),
    (("chargeback",), "Chargeback"),
    (("dispute",), "Dispute"),
    (("case_open", "case_opened"), "Issue / case"),
    (("out_for_delivery",), "Out for delivery"),
    (("delivered",), "Delivered"),
    (("in_transit",), "In transit"),
    (("carrier_accepted", "picked_up", "collected"), "Picked up"),
    (("marketplace_dispatch_confirmed", "label_assigned", "dispatched", "shipped"), "Shipped"),
    (("marketplace_sale", "sale", "order_received", "new_order", "confirmed", "unshipped"), "Get ready to dispatch"),
)

_ACTION_LABELS = {
    "Get ready to dispatch",
    "Partially dispatched",
    "Return requested",
    "Refund requested",
    "Cancellation requested",
    "Replacement requested",
    "Chargeback",
    "Dispute",
    "Issue / case",
    "Late",
}


def _normalise(value) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _commercial_label(event: dict) -> str | None:
    values = " ".join(
        _normalise(event.get(key))
        for key in (
            "event_type",
            "lifecycle_status",
            "status",
            "log_type",
            "source",
            "title",
            "message",
        )
        if event.get(key) not in (None, "")
    )
    if not values:
        return None
    for tokens, label in _COMMERCIAL_LABELS:
        if any(token in values for token in tokens):
            return label
    return None


def _event_to_bell_record(event: dict) -> dict | None:
    """Pure presentation mapper retained for existing event-format callers."""
    label = _commercial_label(event)
    if not label:
        return None

    revision = int(event.get("revision") or 0)
    order_id = str(event.get("order_id") or event.get("marketplace_order_id") or "").strip()
    sku = str(event.get("seller_sku") or event.get("sku") or "").strip()
    platform = str(event.get("platform") or "Marketplace").strip() or "Marketplace"
    quantity = event.get("quantity")
    carrier = str(event.get("carrier") or event.get("provider") or "").strip()
    product_title = str(event.get("product_title") or "").strip()
    subject = product_title or order_id or "Marketplace order"
    title = f"{label} · {platform} · {subject}"

    return {
        "event_key": f"runtime:{revision}:{_normalise(label)}:{order_id}:{sku}",
        "id": f"runtime:{revision}",
        "log_type": "marketplace_sale" if label == "Get ready to dispatch" else "marketplace_lifecycle",
        "platform": platform,
        "title": title,
        "message": title,
        "order_id": order_id,
        "sku": sku,
        "product_title": product_title,
        "quantity": quantity,
        "carrier": carrier,
        "status_label": label,
        "requires_action": label in _ACTION_LABELS,
        "created_at": event.get("published_at"),
    }


def _restore_pending_fbm_visibility() -> None:
    """Keep valid FBM Pending rows visible without changing tab authority."""
    from services import governed_fbm_page_alignment as page

    if getattr(page, "_bt38_pending_visibility_restored", False):
        return

    def aligned_visible_eligible(row, profile=None):
        if not page._is_fbm_eligible(row):
            return False

        if page._platform(row).strip().lower() != "amazon":
            return True

        fulfillment = str(getattr(row, "fulfillment_type", "") or "").strip().upper()
        profile_channel = str(getattr(profile, "fulfillment_channel", "") or "").strip().upper() if profile else ""

        if profile_channel in {"AFN", "FBA", "MCF"}:
            return False
        if profile_channel in {"MFN", "FBM"}:
            return True
        return fulfillment in {"MFN", "FBM"}

    page._workspace_fbm_eligible = aligned_visible_eligible
    page._bt38_pending_visibility_restored = True


def _fbm_row_visibility_script() -> str:
    return r'''
<script id="bt38FbmRowVisibilityAlignment">
(function(){
  function clearStaleDisplayOverride(){
    document.querySelectorAll('tr.fbm-order-row').forEach(function(row){
      row.style.removeProperty('display');
    });
  }

  document.addEventListener('click',function(event){
    var tab=event.target&&event.target.closest?event.target.closest('.fbm-lifecycle-tab[data-fbm-tab]'):null;
    if(tab)queueMicrotask(clearStaleDisplayOverride);
  },false);

  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',clearStaleDisplayOverride,{once:true});
  }else{
    clearStaleDisplayOverride();
  }
  window.addEventListener('load',clearStaleDisplayOverride,{once:true});
})();
</script>
'''


def _align_ready_landing_html(html: str) -> str:
    """Keep Ready to dispatch as the first/default workflow using rendered HTML only."""
    html = html.replace(
        "var sessionDefaults={tab:'pending',search:'',dirty:false};",
        "var sessionDefaults={tab:'ready_dispatch',search:'',dirty:false};",
    )
    html = html.replace(
        "(saved.tab&&labels[saved.tab]?saved.tab:'pending')",
        "((saved.tab&&labels[saved.tab]&&saved.tab!=='pending')?saved.tab:'ready_dispatch')",
    )
    html = html.replace(
        "addWorkflowButton(tabBar,'pending','Pending');\n  addWorkflowButton(tabBar,'ready_dispatch','Ready to dispatch');",
        "addWorkflowButton(tabBar,'ready_dispatch','Ready to dispatch');\n  addWorkflowButton(tabBar,'pending','Pending');",
    )

    # Never hydrate on browser wake. The existing governed event handoff may mark
    # rendered state dirty, but another read happens only on an explicit user/page
    # action already owned by the application.
    html = html.replace("hydrateBellAfterWake();", "stale = true;")

    # Bell presentation must not mark authoritative work complete merely because
    # the offcanvas was opened.
    html = re.sub(
        r"function updateUnread\(\) \{.*?\n        \}\n\n        function markSeen\(\) \{.*?\n        \}",
        "function updateUnread() {\n            const pending = records.filter(function(record) { return record && record.requires_action === true; }).length;\n            setBadge(pending);\n            setBellLight(pending > 0);\n        }\n\n        function markSeen() {\n            updateUnread();\n        }",
        html,
        count=1,
        flags=re.S,
    )

    html = html.replace('data-feather="bell-off" class="mb-2"', 'data-feather="bell" class="mb-2"')

    if "fbm-order-row" in html and 'id="bt38FbmRowVisibilityAlignment"' not in html:
        marker = "</body>"
        script = _fbm_row_visibility_script()
        html = html.replace(marker, script + marker, 1) if marker in html else html + script
    return html


def _align_browser_pressure_response(response):
    if response.status_code != 200:
        return response

    content_type = str(response.content_type or "").lower()
    path = request.path.rstrip("/") or "/"

    if "text/html" in content_type:
        response.set_data(_align_ready_landing_html(response.get_data(as_text=True)))
        return response

    if path == "/static/js/fbm_tracking_journey.js" and "javascript" in content_type:
        if response.direct_passthrough:
            response.direct_passthrough = False
        body = response.get_data(as_text=True)
        body = body.replace(
            "window.addEventListener('bt38-marketplace-event', refreshFbmFromGovernedEvent);",
            "window.addEventListener('bt38-marketplace-event', function(){ document.documentElement.dataset.bt38FbmCommittedStateDirty='1'; });",
        )
        response.set_data(body)
    return response


def install_governed_fbm_ready_landing_alignment(app) -> None:
    _restore_pending_fbm_visibility()

    endpoint = "governed_fbm.fbm_page"
    current = app.view_functions.get(endpoint)
    if current is not None and not getattr(current, "_bt38_ready_landing_alignment", False):
        @login_required
        def ready_landing_page():
            response = make_response(current())
            if response.status_code == 200 and "text/html" in str(response.content_type or "").lower():
                response.set_data(_align_ready_landing_html(response.get_data(as_text=True)))
            return response

        ready_landing_page._bt38_ready_landing_alignment = True
        app.view_functions[endpoint] = ready_landing_page

    # Deliberately leave governed.governed_ui_notifications untouched. The
    # existing logical-bell alignment owns presentation over its already-held
    # event snapshot; this module must never replace it with a DB-backed reader.

    if not getattr(app, "_bt38_db_pressure_response_alignment", False):
        app.after_request(_align_browser_pressure_response)
        app._bt38_db_pressure_response_alignment = True

    app.logger.info(
        "BT38 FBM ready landing aligned: Ready to dispatch first; bell endpoint preserved; zero DB/provider reads added"
    )
