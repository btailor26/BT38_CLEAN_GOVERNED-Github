"""Align the existing FBM workspace to the BT38 browser-session workflow.

The registered /fbm page remains the one workspace and existing order table.
The DB supplies the complete relevant persisted FBM working set on page load.
History, lifecycle tabs, search and pagination then navigate that rendered working
set locally in the browser. No marketplace/provider read and no DB read/write is
introduced by those page controls.
"""
from __future__ import annotations

import json

from flask import g, make_response
from flask_login import login_required
from sqlalchemy import func
from sqlalchemy.orm import joinedload

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


def _complete_fbm_page_rows(_limit: int) -> tuple[list[MarketplaceOrder], bool]:
    """Load the complete relevant persisted FBM working set once for local navigation."""
    candidates = (
        db.session.query(MarketplaceOrder)
        .filter(
            func.upper(func.coalesce(MarketplaceOrder.fulfillment_type, "")).notin_(("FBA", "AFN", "MCF")),
            ~func.lower(func.coalesce(MarketplaceOrder.status, "")).like("mcf_%"),
            MarketplaceOrder.store_id.isnot(None),
            MarketplaceOrder.marketplace_order_id.isnot(None),
        )
        .options(joinedload(MarketplaceOrder.store), joinedload(MarketplaceOrder.warehouse_stock))
        .order_by(MarketplaceOrder.id.desc())
        .all()
    )
    rows = global_search._canonical_order_rows(candidates)
    g._bt38_fbm_page_working_rows = list(rows)
    return list(rows), False


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
            "created_at": row.created_at.isoformat() if getattr(row, "created_at", None) else None,
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


def _inject(html: str, payload: dict[str, dict], fba_count: int) -> str:
    html = _align_cofi_ui(html)
    data = json.dumps(payload, separators=(",", ":"), sort_keys=True).replace("</", "<\\/")
    marker = "</body>"
    block = f'''<style id="bt38FbmLifecycleTabsAlignment">
.fbm-lifecycle-tabs{{display:flex;gap:.35rem;overflow-x:auto;padding:.45rem .5rem;border-bottom:1px solid #dee2e6;background:var(--bs-body-bg,#fff);scrollbar-width:thin}}.fbm-lifecycle-tab{{white-space:nowrap;border:1px solid #d0d5dd;background:transparent;border-radius:.375rem;padding:.38rem .62rem;font-size:.78rem;font-weight:650;color:inherit;text-decoration:none}}.fbm-lifecycle-tab.active{{background:#212529;color:#fff;border-color:#212529}}.fbm-lifecycle-tab .badge{{margin-left:.3rem;font-size:.62rem}}.fbm-shipping-cost{{white-space:nowrap;font-weight:650}}.fbm-shipping-cost-pending{{font-size:.72rem;color:#667085;white-space:nowrap}}tr.fbm-order-row[data-fbm-history-match="0"]{{display:none!important}}
</style>
<script id="bt38FbmLifecycleTabsData" type="application/json">{data}</script>
<script id="bt38FbmLifecycleTabsScript">
(function(){{
  var table=document.querySelector('.fbm-orders-table');
  var dataNode=document.getElementById('bt38FbmLifecycleTabsData');
  if(!table||!dataNode) return;
  var data={{}};try{{data=JSON.parse(dataNode.textContent||'{{}}')}}catch(e){{return;}}
  var card=table.closest('.card');if(!card)return;
  var body=table.querySelector('tbody');
  var rows=Array.from(body.querySelectorAll('tr.fbm-order-row'));
  var labels={{ready_dispatch:'Ready to dispatch',pending:'Pending',dispatched:'Dispatched',cancelled:'Cancelled',replacements:'Replacement',refunds:'Refunds'}};
  var sessionDefaults={{tab:'pending',search:'',range:'3d',from:'',to:'',dirty:false}};
  var saved=(window.BT38&&typeof window.BT38.getPageSession==='function')?window.BT38.getPageSession('fbm',sessionDefaults):sessionDefaults;
  var params=new URLSearchParams(window.location.search);
  var legacyTab=params.get('fbm_tab');
  var legacySearch=params.get('search')||params.get('q');
  var active=(legacyTab&&labels[legacyTab])?legacyTab:(saved.tab&&labels[saved.tab]?saved.tab:'pending');
  var search=String(legacySearch!=null?legacySearch:(saved.search||'')).trim().toLowerCase();
  var range=String(saved.range||params.get('fbm_range')||'3d').toLowerCase();
  var from=String(saved.from||params.get('fbm_from')||'');
  var to=String(saved.to||params.get('fbm_to')||'');
  function saveSession(extra){{var next=Object.assign({{tab:active,search:search,range:range,from:from,to:to,dirty:false}},extra||{{}});if(window.BT38&&typeof window.BT38.setPageSession==='function')window.BT38.setPageSession('fbm',next);return next;}}
  var searchInput=document.getElementById('bt38FbmGlobalSearchInput');
  var clearSearch=document.getElementById('bt38FbmGlobalSearchClear');
  var historyForm=document.getElementById('bt38FbmControls');
  var rangeInput=document.getElementById('bt38FbmRangeSelect')||document.getElementById('bt38FbmRange');
  var fromInput=historyForm&&historyForm.querySelector('[name="fbm_from"]');
  var toInput=historyForm&&historyForm.querySelector('[name="fbm_to"]');
  if(searchInput)searchInput.value=search;
  if(rangeInput)rangeInput.value=range;
  if(fromInput)fromInput.value=from;
  if(toInput)toInput.value=to;
  function ensureCostHeader(){{var head=table.querySelector('thead tr');if(!head||head.querySelector('[data-fbm-shipping-cost="1"]'))return;var th=document.createElement('th');th.textContent='Shipping cost';th.dataset.fbmShippingCost='1';head.insertBefore(th,head.lastElementChild);}}
  function addCostCell(row,info){{if(row.querySelector('[data-fbm-shipping-cost="1"]'))return;var td=document.createElement('td');td.dataset.fbmShippingCost='1';if(info.shipping_cost_confirmed){{td.className='fbm-shipping-cost';try{{td.textContent=new Intl.NumberFormat('en-GB',{{style:'currency',currency:info.shipping_currency||'GBP'}}).format(info.shipping_cost)}}catch(e){{td.textContent=(info.shipping_currency||'GBP')+' '+Number(info.shipping_cost).toFixed(2)}}}}else{{td.className='fbm-shipping-cost-pending';td.textContent='Pending / unavailable'}}row.insertBefore(td,row.lastElementChild);}}
  ensureCostHeader();
  rows.forEach(function(row){{var info=data[row.dataset.orderId]||{{queue:'unclassified',shipping_cost_confirmed:false,created_at:null}};row.dataset.fbmQueue=info.queue;row.dataset.fbmCreatedAt=info.created_at||'';row.dataset.fbmSearch=(row.textContent||'').toLowerCase();addCostCell(row,info)}});
  function localDay(value){{if(!value)return null;var d=new Date(value);return isNaN(d.getTime())?null:new Date(d.getFullYear(),d.getMonth(),d.getDate());}}
  function historyBounds(){{var today=new Date();today=new Date(today.getFullYear(),today.getMonth(),today.getDate());if(range==='custom'){{var a=from?new Date(from+'T00:00:00'):null,b=to?new Date(to+'T23:59:59'):null;return {{start:a,end:b}};}}var days={{'3d':3,'7d':7,'30d':30,'90d':90,'1y':365}}[range]||3;var start=new Date(today);start.setDate(start.getDate()-(days-1));var end=new Date(today);end.setHours(23,59,59,999);return {{start:start,end:end}};}}
  function inHistory(row){{var d=localDay(row.dataset.fbmCreatedAt);if(!d)return false;var bounds=historyBounds();if(bounds.start&&d<bounds.start)return false;if(bounds.end&&d>bounds.end)return false;return true;}}
  function localCounts(){{var result={{ready_dispatch:0,pending:0,dispatched:0,cancelled:0,replacements:0,refunds:0}};rows.forEach(function(row){{if(!inHistory(row))return;var q=row.dataset.fbmQueue;if(Object.prototype.hasOwnProperty.call(result,q))result[q]+=1;}});return result;}}
  function addWorkflowButton(bar,name,label){{var button=document.createElement('button');button.type='button';button.dataset.fbmTab=name;button.className='fbm-lifecycle-tab'+(active===name?' active':'');button.innerHTML=label+' <span class="badge bg-light text-dark border">0</span>';button.addEventListener('click',function(){{active=name;saveSession();render()}});bar.appendChild(button)}}
  function addTruthLink(bar,label,href,count){{var link=document.createElement('a');link.className='fbm-lifecycle-tab';link.href=href;link.innerHTML=label+' <span class="badge bg-light text-dark border">'+Number(count||0)+'</span>';bar.appendChild(link)}}
  var tabBar=document.createElement('div');tabBar.className='fbm-lifecycle-tabs';
  addWorkflowButton(tabBar,'pending','Pending');addWorkflowButton(tabBar,'ready_dispatch','Ready to dispatch');addWorkflowButton(tabBar,'dispatched','Dispatched');addWorkflowButton(tabBar,'cancelled','Cancelled');addTruthLink(tabBar,'FBA','/governed/amazon-fba-stock',{int(fba_count)});addWorkflowButton(tabBar,'replacements','Replacement');addWorkflowButton(tabBar,'refunds','Refunds');
  var header=card.querySelector('.card-header');if(header)header.insertAdjacentElement('afterend',tabBar);else card.insertBefore(tabBar,card.firstChild);
  function handoffToExistingPager(matched){{var controller=window.BT38&&window.BT38.PageController;var pages=window.BT38&&window.BT38.pages;var state=pages&&(pages.fbm||pages.FBM);if(!controller||!state||!Array.isArray(state.rows)||typeof controller.renderPage!=='function')return false;var set=new Set(matched);state.filteredRows=state.rows.filter(function(entry){{return entry&&set.has(entry.el)}});state.currentPage=1;controller.renderPage(state.name);return true;}}
  function refreshBadges(){{var counts=localCounts();tabBar.querySelectorAll('[data-fbm-tab]').forEach(function(button){{var badge=button.querySelector('.badge');if(badge)badge.textContent=Number(counts[button.dataset.fbmTab]||0)}});}}
  var initialRender=true;
  function render(){{
    rows.forEach(function(row){{row.dataset.fbmHistoryMatch=inHistory(row)?'1':'0'}});
    var counts=localCounts();
    if(initialRender&&Number(counts[active]||0)===0){{var fallback=['pending','ready_dispatch','dispatched','replacements','refunds','cancelled'].find(function(name){{return Number(counts[name]||0)>0}});if(fallback)active=fallback;}}
    initialRender=false;
    var matched=rows.filter(function(row){{return row.dataset.fbmHistoryMatch==='1'&&row.dataset.fbmQueue===active&&(!search||String(row.dataset.fbmSearch||'').indexOf(search)>=0)}});
    var matchedSet=new Set(matched);
    var paged=handoffToExistingPager(matched);
    rows.forEach(function(row){{if(!matchedSet.has(row))row.hidden=true;else if(!paged)row.hidden=false}});
    refreshBadges();
    tabBar.querySelectorAll('[data-fbm-tab]').forEach(function(button){{var selected=button.dataset.fbmTab===active;button.classList.toggle('active',selected);button.setAttribute('aria-selected',selected?'true':'false')}});
    var title=card.querySelector('.card-header .fw-semibold');if(title&&labels[active])title.textContent=labels[active];
    var actionable=active==='ready_dispatch';var actionArea=document.getElementById('readyToShipSelected');var selectAll=document.getElementById('selectAllOrders');if(actionArea)actionArea.classList.toggle('d-none',!actionable);if(selectAll)selectAll.disabled=!actionable;
    rows.forEach(function(row){{var cb=row.querySelector('.fbm-order-checkbox');if(cb){{cb.checked=false;cb.closest('td').classList.toggle('invisible',!actionable)}}var option=row.querySelector('.fbm-shipping-options');if(option)option.classList.toggle('d-none',!actionable)}});saveSession();
  }}
  function applyHistory(event){{if(event){{event.preventDefault();event.stopPropagation();}}range=String(rangeInput&&rangeInput.value||'3d').toLowerCase();from=String(fromInput&&fromInput.value||'');to=String(toInput&&toInput.value||'');saveSession();render();}}
  if(historyForm)historyForm.addEventListener('submit',applyHistory,true);
  if(rangeInput)rangeInput.addEventListener('change',applyHistory,true);
  if(fromInput)fromInput.addEventListener('change',applyHistory,true);
  if(toInput)toInput.addEventListener('change',applyHistory,true);
  if(searchInput)searchInput.addEventListener('input',function(){{search=String(searchInput.value||'').trim().toLowerCase();saveSession();render()}});
  if(clearSearch)clearSearch.addEventListener('click',function(event){{event.preventDefault();if(searchInput)searchInput.value='';search='';saveSession();render()}});
  window.BT38FBMApplyCommittedSnapshot=function(nextData){{data=nextData||data;rows.forEach(function(row){{var info=data[row.dataset.orderId];if(info){{row.dataset.fbmQueue=info.queue||row.dataset.fbmQueue;row.dataset.fbmCreatedAt=info.created_at||row.dataset.fbmCreatedAt}}}});render()}};
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

    # Warehouse-pattern alignment: the server establishes the complete persisted
    # working set once; normal FBM navigation never asks the DB to rebuild it.
    page_alignment._latest_distinct_fbm_rows = _complete_fbm_page_rows

    @login_required
    def aligned_fbm_page():
        original = current_view()
        response = make_response(original)
        if response.status_code != 200 or not response.mimetype.startswith("text/html"):
            return response
        rows = list(getattr(g, "_bt38_fbm_page_working_rows", []) or [])
        if not rows:
            rows = list(getattr(g, "_bt38_fbm_session_rows", []) or [])
        payload = _presentation(rows)
        response.set_data(_inject(response.get_data(as_text=True), payload, _fba_count()))
        return response

    app.view_functions[endpoint] = aligned_fbm_page
    app._bt38_fbm_dispatch_queue_alignment_installed = True
    app.logger.info("BT38 FBM lifecycle aligned: complete persisted page working set loaded once; History, lifecycle, search and pager are browser-local; no navigation DB/provider read")
