"""Align the existing FBM workspace to the BT38 browser-session workflow.

The registered /fbm page remains the one workspace and existing order table.
One selected persisted history snapshot is the authority for every lifecycle tab,
its badge, search and pagination. No marketplace/provider/DB write is introduced.
"""
from __future__ import annotations

import json

from flask import g, make_response
from flask_login import login_required

from extensions import db
from models import MarketplaceOrder
from shipping_spend_models import ShippingSpendLedger
from services import governed_fbm_global_search_alignment as global_search
from services import governed_fbm_page_alignment as page_alignment


_WORKFLOW_LABELS = {
    "ready_dispatch": "Ready to dispatch",
    "pending": "Pending",
    "dispatched": "Dispatched",
    "cancelled": "Cancelled",
    "replacements": "Replacement",
    "refunds": "Refunds",
}
_DISPATCHED_MARKETPLACE_STATUSES = {
    "shipped", "dispatched", "delivered", "fulfilled", "completed",
    "partially_shipped", "partiallyshipped", "picked_up_by_carrier",
    "pickedupbycarrier", "in_transit", "intransit", "out_for_delivery",
    "outfordelivery",
}
_ADDITIONAL_SHIPMENT_PREFIXES = (
    "packlink_return:",
    "packlink_replacement:",
)


def _marketplace_platform_for(row: MarketplaceOrder) -> str:
    store = getattr(row, "store", None)
    return str(
        getattr(store, "platform", None)
        or getattr(row, "platform", None)
        or getattr(row, "marketplace", None)
        or ""
    ).strip().lower()


def _outbound_label_handoff_reached(shipment) -> bool:
    """Treat only the original outbound label as the browser dispatch handoff."""
    if shipment is None:
        return False
    purchase_key = str(getattr(shipment, "purchase_key", "") or "").strip().lower()
    if purchase_key.startswith(_ADDITIONAL_SHIPMENT_PREFIXES):
        return False
    purchase_status = str(getattr(shipment, "purchase_status", "") or "").strip().lower()
    return bool(
        getattr(shipment, "label_purchased_at", None) is not None
        or purchase_status == "purchased"
    )


def _dispatch_truth_reached(row: MarketplaceOrder, shipment=None) -> bool:
    """Return persisted dispatch truth independently of the browser label handoff."""
    status = str(getattr(row, "status", "") or "").strip().lower()
    return bool(
        status in _DISPATCHED_MARKETPLACE_STATUSES
        or getattr(row, "tracking_number", None)
        or getattr(row, "shipped_at", None)
        or (shipment and getattr(shipment, "tracking_number", None))
        or (shipment and getattr(shipment, "carrier_accepted_at", None))
        or (shipment and getattr(shipment, "first_movement_at", None))
        or (shipment and getattr(shipment, "delivered_at", None))
    )


def _aligned_workflow_queue_for(row: MarketplaceOrder, shipment=None) -> str:
    """Classify every lifecycle tab from the same persisted truth hierarchy."""
    status = str(getattr(row, "status", "") or "").strip().lower()
    reason = global_search._status_reason(status)
    if status in global_search._CANCELLED_STATUSES or status.startswith("cancel"):
        return "cancelled"
    if status == "pending" and "amazon" in _marketplace_platform_for(row):
        return "pending"
    if reason:
        return reason
    if _outbound_label_handoff_reached(shipment):
        return "dispatched"
    return "dispatched" if _dispatch_truth_reached(row, shipment) else "ready_dispatch"


def _health_route_state_from_marketplace_lifecycle(row: MarketplaceOrder) -> str:
    queue = _aligned_workflow_queue_for(row)
    if queue == "dispatched":
        return "Dispatched"
    if queue == "ready_dispatch":
        return "Ready for FBM routing"
    if queue == "pending":
        return "Pending"
    if queue == "cancelled":
        return "Cancelled"
    return queue


global_search.workflow_queue_for = _aligned_workflow_queue_for
workflow_queue_for = global_search.workflow_queue_for
page_alignment._route_state = _health_route_state_from_marketplace_lifecycle


def _presentation(rows: list[MarketplaceOrder]) -> dict[str, dict]:
    shipments = page_alignment._shipment_map(rows)
    shipment_ids = sorted({int(s.id) for s in shipments.values() if s and getattr(s, "id", None)})
    spend_by_shipment: dict[int, ShippingSpendLedger] = {}
    if shipment_ids:
        spend_rows = (
            db.session.query(ShippingSpendLedger)
            .filter(ShippingSpendLedger.confirmed.is_(True))
            .filter(ShippingSpendLedger.shipment_id.in_(shipment_ids))
            .order_by(ShippingSpendLedger.recorded_at.desc(), ShippingSpendLedger.id.desc())
            .all()
        )
        for spend in spend_rows:
            shipment_id = int(spend.shipment_id)
            if shipment_id not in spend_by_shipment:
                spend_by_shipment[shipment_id] = spend

    payload: dict[str, dict] = {}
    for row in rows:
        key = (int(row.store_id), str(row.marketplace_order_id))
        shipment = shipments.get(key)
        queue = workflow_queue_for(row, shipment)
        spend = spend_by_shipment.get(int(shipment.id)) if shipment and getattr(shipment, "id", None) else None
        payload[str(row.id)] = {
            "queue": queue,
            "status": str(getattr(row, "status", "") or "").strip().lower(),
            "shipping_cost": float(spend.amount) if spend is not None else None,
            "shipping_currency": str(spend.currency or "GBP").upper() if spend is not None else None,
            "shipping_cost_confirmed": spend is not None,
        }
    return payload


def _counts_from_payload(payload: dict[str, dict]) -> dict[str, int]:
    counts = {name: 0 for name in _WORKFLOW_LABELS}
    for info in payload.values():
        queue = str(info.get("queue") or "")
        if queue in counts:
            counts[queue] += 1
    return counts


def _selected_history_counts() -> dict[str, int]:
    """Count every lifecycle from the complete selected persisted history."""
    rows = list(getattr(g, "_bt38_fbm_health_rows", []) or [])
    if not rows:
        return _counts_from_payload({})
    profiles = page_alignment._profile_map([row for row in rows if _marketplace_platform_for(row) == "amazon"])
    eligible_rows: list[MarketplaceOrder] = []
    for row in rows:
        if row.store_id is None or not row.marketplace_order_id:
            continue
        key = (int(row.store_id), str(row.marketplace_order_id))
        profile = profiles.get(key) if _marketplace_platform_for(row) == "amazon" else None
        if page_alignment._workspace_fbm_eligible(row, profile):
            eligible_rows.append(row)
    shipments = page_alignment._shipment_map(eligible_rows)
    counts = {name: 0 for name in _WORKFLOW_LABELS}
    for row in eligible_rows:
        shipment = shipments.get((int(row.store_id), str(row.marketplace_order_id)))
        queue = workflow_queue_for(row, shipment)
        if queue in counts:
            counts[queue] += 1
    return counts


def _fba_count() -> int:
    try:
        return int(db.session.query(MarketplaceOrder.id).filter(
            db.func.upper(db.func.coalesce(MarketplaceOrder.fulfillment_type, "")).in_(("FBA", "AFN"))
        ).count())
    except Exception:
        return 0


def _align_cofi_ui(html: str) -> str:
    replacements = {
        'alt="BT38 shipping guide"': 'alt="Cofi"',
        "BT38 will keep the queue visible.": "Cofi will keep the queue visible.",
        "Everything that needs a shipping action is clear for this period.": "Everything that needs a shipping action is clear. Cofi will keep watching the work queue.",
        "Work through the important shipping actions first.": "Cofi has put the important shipping actions first.",
        ">Ready to Ship<": ">Ready to dispatch<",
        "Ready to Ship or Shipping options.": "Ready to dispatch or Shipping options.",
    }
    for old, new in replacements.items():
        html = html.replace(old, new)
    return html


def _inject(html: str, payload: dict[str, dict], counts: dict[str, int], fba_count: int, truncated: bool) -> str:
    html = _align_cofi_ui(html)
    data = json.dumps(payload, separators=(",", ":"), sort_keys=True).replace("</", "<\\/")
    count_data = json.dumps(counts, separators=(",", ":"), sort_keys=True).replace("</", "<\\/")
    marker = "</body>"
    block = f'''<style id="bt38FbmLifecycleTabsAlignment">
.fbm-lifecycle-tabs{{display:flex;gap:.35rem;overflow-x:auto;padding:.45rem .5rem;border-bottom:1px solid #dee2e6;background:var(--bs-body-bg,#fff);scrollbar-width:thin}}.fbm-lifecycle-tab{{white-space:nowrap;border:1px solid #d0d5dd;background:transparent;border-radius:.375rem;padding:.38rem .62rem;font-size:.78rem;font-weight:650;color:inherit;text-decoration:none}}.fbm-lifecycle-tab.active{{background:#212529;color:#fff;border-color:#212529}}.fbm-lifecycle-tab .badge{{margin-left:.3rem;font-size:.62rem}}.fbm-shipping-cost{{white-space:nowrap;font-weight:650}}.fbm-shipping-cost-pending{{font-size:.72rem;color:#667085;white-space:nowrap}}
</style>
<script id="bt38FbmLifecycleTabsData" type="application/json">{data}</script>
<script id="bt38FbmLifecycleCountsData" type="application/json">{count_data}</script>
<script id="bt38FbmLifecycleTabsScript">
(function(){{
  var table=document.querySelector('.fbm-orders-table');
  var dataNode=document.getElementById('bt38FbmLifecycleTabsData');
  var countNode=document.getElementById('bt38FbmLifecycleCountsData');
  if(!table||!dataNode||!countNode) return;
  var data={{}},counts={{}};try{{data=JSON.parse(dataNode.textContent||'{{}}');counts=JSON.parse(countNode.textContent||'{{}}')}}catch(e){{return;}}
  var card=table.closest('.card');if(!card)return;
  var body=table.querySelector('tbody');
  var rows=Array.from(body.querySelectorAll('tr.fbm-order-row'));
  var labels={{ready_dispatch:'Ready to dispatch',pending:'Pending',dispatched:'Dispatched',cancelled:'Cancelled',replacements:'Replacement',refunds:'Refunds'}};
  var sessionDefaults={{tab:'pending',search:'',dirty:false}};
  var saved=(window.BT38&&typeof window.BT38.getPageSession==='function')?window.BT38.getPageSession('fbm',sessionDefaults):sessionDefaults;
  var params=new URLSearchParams(window.location.search);
  var legacyTab=params.get('fbm_tab');
  var legacySearch=params.get('search')||params.get('q');
  var active=(legacyTab&&labels[legacyTab])?legacyTab:(saved.tab&&labels[saved.tab]?saved.tab:'pending');
  var search=String(legacySearch!=null?legacySearch:(saved.search||'')).trim().toLowerCase();
  function saveSession(extra){{var next=Object.assign({{tab:active,search:search,dirty:false}},extra||{{}});if(window.BT38&&typeof window.BT38.setPageSession==='function')window.BT38.setPageSession('fbm',next);return next;}}
  var searchInput=document.getElementById('bt38FbmGlobalSearchInput');
  var clearSearch=document.getElementById('bt38FbmGlobalSearchClear');
  if(searchInput)searchInput.value=search;
  function ensureCostHeader(){{var head=table.querySelector('thead tr');if(!head||head.querySelector('[data-fbm-shipping-cost="1"]'))return;var th=document.createElement('th');th.textContent='Shipping cost';th.dataset.fbmShippingCost='1';head.insertBefore(th,head.lastElementChild);}}
  function addCostCell(row,info){{if(row.querySelector('[data-fbm-shipping-cost="1"]'))return;var td=document.createElement('td');td.dataset.fbmShippingCost='1';if(info.shipping_cost_confirmed){{td.className='fbm-shipping-cost';try{{td.textContent=new Intl.NumberFormat('en-GB',{{style:'currency',currency:info.shipping_currency||'GBP'}}).format(info.shipping_cost)}}catch(e){{td.textContent=(info.shipping_currency||'GBP')+' '+Number(info.shipping_cost).toFixed(2)}}}}else{{td.className='fbm-shipping-cost-pending';td.textContent='Pending / unavailable'}}row.insertBefore(td,row.lastElementChild);}}
  ensureCostHeader();
  rows.forEach(function(row){{var info=data[row.dataset.orderId]||{{queue:'unclassified',shipping_cost_confirmed:false}};row.dataset.fbmQueue=info.queue;row.dataset.fbmSearch=(row.textContent||'').toLowerCase();addCostCell(row,info)}});
  function addWorkflowButton(bar,name,label){{var button=document.createElement('button');button.type='button';button.dataset.fbmTab=name;button.className='fbm-lifecycle-tab'+(active===name?' active':'');button.innerHTML=label+' <span class="badge bg-light text-dark border">'+Number(counts[name]||0)+'</span>';button.addEventListener('click',function(){{active=name;saveSession();render()}});bar.appendChild(button)}}
  function addTruthLink(bar,label,href,count){{var link=document.createElement('a');link.className='fbm-lifecycle-tab';link.href=href;link.innerHTML=label+' <span class="badge bg-light text-dark border">'+Number(count||0)+'</span>';bar.appendChild(link)}}
  var tabBar=document.createElement('div');tabBar.className='fbm-lifecycle-tabs';
  addWorkflowButton(tabBar,'pending','Pending');addWorkflowButton(tabBar,'ready_dispatch','Ready to dispatch');addWorkflowButton(tabBar,'dispatched','Dispatched');addWorkflowButton(tabBar,'cancelled','Cancelled');addTruthLink(tabBar,'FBA','/governed/amazon-fba-stock',{int(fba_count)});addWorkflowButton(tabBar,'replacements','Replacement');addWorkflowButton(tabBar,'refunds','Refunds');
  var header=card.querySelector('.card-header');if(header)header.insertAdjacentElement('afterend',tabBar);else card.insertBefore(tabBar,card.firstChild);
  function handoffToExistingPager(matched){{var controller=window.BT38&&window.BT38.PageController;var pages=window.BT38&&window.BT38.pages;var state=pages&&(pages.fbm||pages.FBM);if(!controller||!state||!Array.isArray(state.rows)||typeof controller.renderPage!=='function')return false;var set=new Set(matched);state.filteredRows=state.rows.filter(function(entry){{return entry&&set.has(entry.el)}});state.currentPage=1;controller.renderPage(state.name);return true;}}
  function render(){{
    var matched=rows.filter(function(row){{return row.dataset.fbmQueue===active&&(!search||String(row.dataset.fbmSearch||'').indexOf(search)>=0)}});
    var matchedSet=new Set(matched);
    var paged=handoffToExistingPager(matched);
    /* Lifecycle authority is absolute: a pager may further hide matched rows for
       its current page, but it may never re-show a row outside the active tab. */
    rows.forEach(function(row){{if(!matchedSet.has(row))row.hidden=true;else if(!paged)row.hidden=false}});
    tabBar.querySelectorAll('[data-fbm-tab]').forEach(function(button){{var selected=button.dataset.fbmTab===active;button.classList.toggle('active',selected);button.setAttribute('aria-selected',selected?'true':'false')}});
    var title=card.querySelector('.card-header .fw-semibold');if(title&&labels[active])title.textContent=labels[active];
    var actionable=active==='ready_dispatch';var actionArea=document.getElementById('readyToShipSelected');var selectAll=document.getElementById('selectAllOrders');if(actionArea)actionArea.classList.toggle('d-none',!actionable);if(selectAll)selectAll.disabled=!actionable;
    rows.forEach(function(row){{var cb=row.querySelector('.fbm-order-checkbox');if(cb){{cb.checked=false;cb.closest('td').classList.toggle('invisible',!actionable)}}var option=row.querySelector('.fbm-shipping-options');if(option)option.classList.toggle('d-none',!actionable)}});saveSession();
  }}
  if(searchInput)searchInput.addEventListener('input',function(){{search=String(searchInput.value||'').trim().toLowerCase();saveSession();render()}});
  if(clearSearch)clearSearch.addEventListener('click',function(event){{event.preventDefault();if(searchInput)searchInput.value='';search='';saveSession();render()}});
  window.BT38FBMApplyCommittedSnapshot=function(nextData,nextCounts){{data=nextData||data;counts=nextCounts||counts;rows.forEach(function(row){{var info=data[row.dataset.orderId];if(info)row.dataset.fbmQueue=info.queue||row.dataset.fbmQueue}});tabBar.querySelectorAll('[data-fbm-tab]').forEach(function(button){{var badge=button.querySelector('.badge');if(badge)badge.textContent=Number(counts[button.dataset.fbmTab]||0)}});render()}};
  render();
}})();
</script>'''
    return html.replace(marker, block + marker, 1) if marker in html else html + block


def install_governed_fbm_dispatch_queue_alignment(app) -> None:
    if getattr(app, "_bt38_fbm_dispatch_queue_alignment_installed", False):
        return
    endpoint = "governed_fbm.fbm_page"
    current_view = app.view_functions.get(endpoint)
    if current_view is None:
        raise RuntimeError("governed FBM page endpoint is not registered")

    @login_required
    def aligned_fbm_page():
        original = current_view()
        response = make_response(original)
        if response.status_code != 200 or not response.mimetype.startswith("text/html"):
            return response
        rows = list(getattr(g, "_bt38_fbm_session_rows", []) or [])
        if not rows:
            rows, _ = global_search._session_snapshot_rows()
        truncated = bool(getattr(g, "_bt38_fbm_session_truncated", False))
        payload = _presentation(rows)
        full_counts = _selected_history_counts()
        response.set_data(_inject(response.get_data(as_text=True), payload, full_counts, _fba_count(), truncated))
        return response

    app.view_functions[endpoint] = aligned_fbm_page
    app._bt38_fbm_dispatch_queue_alignment_installed = True
    app.logger.info("BT38 FBM lifecycle aligned: one selected-history truth hierarchy; outbound label handoff preserved; all local tabs obey identical row filter and pager boundary")