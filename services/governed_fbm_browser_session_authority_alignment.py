"""Keep FBM History, lifecycle counts and Health on one browser-session snapshot.

History changes are presentation-only inside the already rendered one-year FBM
working set. Health and lifecycle numbers are recalculated from that same set.
The bottom 15/30/50/100 pager remains independent presentation state.

This module performs persisted BT38 database reads only. It introduces no
marketplace/provider read, write, polling, timer, EventSource or fetch path.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import g
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from extensions import db
from models import MarketplaceOrder
from services import governed_fbm_dispatch_queue_alignment as dispatch
from services import governed_fbm_global_search_alignment as controls
from services import governed_fbm_page_alignment as page
from services.fbm_shipping_state import shipment_confirmation_state

_TZ = ZoneInfo("Europe/London")


def _browser_session_rows(_limit: int):
    """Load at most the History vocabulary's one-year persisted working set once."""
    today = datetime.now(_TZ).date()
    start_local = datetime(
        (today - timedelta(days=364)).year,
        (today - timedelta(days=364)).month,
        (today - timedelta(days=364)).day,
        tzinfo=_TZ,
    )
    start_at = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    candidates = (
        db.session.query(MarketplaceOrder)
        .filter(
            func.upper(func.coalesce(MarketplaceOrder.fulfillment_type, "")).notin_(("FBA", "AFN", "MCF")),
            ~func.lower(func.coalesce(MarketplaceOrder.status, "")).like("mcf_%"),
            MarketplaceOrder.store_id.isnot(None),
            MarketplaceOrder.marketplace_order_id.isnot(None),
            MarketplaceOrder.created_at >= start_at,
        )
        .options(joinedload(MarketplaceOrder.store), joinedload(MarketplaceOrder.warehouse_stock))
        .order_by(MarketplaceOrder.id.desc())
        .all()
    )
    rows = controls._canonical_order_rows(candidates)
    profiles = page._profile_map([
        row for row in rows if dispatch._marketplace_platform_for(row) == "amazon"
    ])
    eligible = []
    for row in rows:
        key = (int(row.store_id), str(row.marketplace_order_id))
        profile = profiles.get(key) if dispatch._marketplace_platform_for(row) == "amazon" else None
        if page._workspace_fbm_eligible(row, profile):
            eligible.append(row)
    g._bt38_fbm_page_working_rows = list(eligible)
    g._bt38_fbm_session_rows = list(eligible)
    return list(eligible), False


def _session_presentation(rows):
    """Expose only persisted facts needed to move Health with History locally."""
    payload = dispatch._bt38_original_presentation(rows)
    shipments = page._shipment_map(rows)
    for row in rows:
        info = payload.get(str(row.id))
        if info is None:
            continue
        key = (int(row.store_id), str(row.marketplace_order_id))
        shipment = shipments.get(key)
        state = shipment_confirmation_state(shipment) if shipment else ""
        mapping_review = False
        if shipment and dispatch._marketplace_platform_for(row) == "amazon":
            review = getattr(shipment, "mapping_review", None)
            mapping_review = bool(review is not None and getattr(review, "status", None) == "under_review")
        status = str(getattr(row, "status", "") or "").strip().lower()
        info.update({
            "platform": dispatch._marketplace_platform_for(row) or "other",
            "shipment_state": state,
            "mapping_review": mapping_review,
            "return_event": status in {"return_requested", "returned"},
        })
    return payload


def _session_health_script() -> str:
    """Make History the sole local scope authority for Health and lifecycle counts."""
    return r'''<script id="bt38FbmBrowserSessionHealthAuthority">
(function(){
  var form=document.getElementById('bt38FbmControls');
  var rangeInput=document.getElementById('bt38FbmRangeSelect')||document.getElementById('bt38FbmRange');
  var fromInput=form&&form.querySelector('[name="fbm_from"]');
  var toInput=form&&form.querySelector('[name="fbm_to"]');
  var dataNode=document.getElementById('bt38FbmLifecycleTabsData');
  var table=document.querySelector('.fbm-orders-table');
  if(!form||!rangeInput||!dataNode||!table)return;
  var data={};try{data=JSON.parse(dataNode.textContent||'{}')}catch(e){return;}
  var rows=Array.from(table.querySelectorAll('tbody tr.fbm-order-row'));

  // History is browser-session state. Remove inherited server-submit behaviour.
  form.onsubmit=function(event){if(event)event.preventDefault();return false;};
  rangeInput.onchange=null;

  function currentSession(){
    var fallback={tab:'pending',search:'',range:'3d',from:'',to:'',dirty:false};
    return (window.BT38&&typeof window.BT38.getPageSession==='function')?window.BT38.getPageSession('fbm',fallback):fallback;
  }
  function bounds(){
    var saved=currentSession()||{};
    var range=String(saved.range||rangeInput.value||'3d').toLowerCase();
    var from=String(saved.from||(fromInput&&fromInput.value)||'');
    var to=String(saved.to||(toInput&&toInput.value)||'');
    var today=new Date();today=new Date(today.getFullYear(),today.getMonth(),today.getDate());
    if(range==='custom')return {range:range,start:from?new Date(from+'T00:00:00'):null,end:to?new Date(to+'T23:59:59'):null,label:(from&&to)?from+' – '+to:'Custom'};
    var days={'3d':3,'7d':7,'30d':30,'90d':90,'1y':365}[range]||3;
    var start=new Date(today);start.setDate(start.getDate()-(days-1));
    var end=new Date(today);end.setHours(23,59,59,999);
    var labels={'3d':'Last 3 days','7d':'Last 7 days','30d':'Last 30 days','90d':'Last 90 days','1y':'Last year'};
    return {range:range,start:start,end:end,label:labels[range]||'Last 3 days'};
  }
  function included(info,b){
    if(!info||!info.created_at)return false;
    var d=new Date(info.created_at);if(isNaN(d.getTime()))return false;
    if(b.start&&d<b.start)return false;if(b.end&&d>b.end)return false;return true;
  }
  function setCard(label,value,tip){
    document.querySelectorAll('.fbm-period-card').forEach(function(card){
      var name=card.querySelector('.fbm-period-label');if(!name||name.textContent.trim()!==label)return;
      var number=card.querySelector('.fbm-period-value');if(number)number.textContent=String(value);
      var help=card.querySelector('.fbm-period-tip');if(help&&tip)help.innerHTML='<div>'+tip+'</div>';
    });
  }
  function syncHealth(){
    var b=bounds();
    var counts={total:0,ready:0,dispatched:0,awaiting:0,overdue:0,returns:0,replacements:0,refunds:0,mapping:0};
    Object.keys(data).forEach(function(id){
      var info=data[id];if(!included(info,b))return;counts.total+=1;
      if(info.queue==='ready_dispatch')counts.ready+=1;
      if(info.queue==='dispatched')counts.dispatched+=1;
      if(info.queue==='replacements')counts.replacements+=1;
      if(info.queue==='refunds')counts.refunds+=1;
      if(info.shipment_state==='awaiting_carrier_acceptance')counts.awaiting+=1;
      if(info.shipment_state==='acceptance_overdue')counts.overdue+=1;
      if(info.return_event)counts.returns+=1;if(info.mapping_review)counts.mapping+=1;
    });
    setCard('Orders',counts.total,counts.total+' FBM orders in this History period');
    setCard('Ready to ship',counts.ready,counts.ready+' orders still need a shipping action');
    setCard('Dispatched',counts.dispatched,counts.dispatched+' orders have dispatch/tracking recorded');
    setCard('Awaiting carrier',counts.awaiting,counts.awaiting+' labels are waiting for carrier acceptance');
    setCard('Carrier overdue',counts.overdue,counts.overdue+' shipments are overdue for carrier acceptance');
    setCard('Returns',counts.returns,counts.returns+' return events recorded in this period');
    setCard('Replacements',counts.replacements,counts.replacements+' replacement events recorded in this period');
    setCard('Refunds / issues',counts.refunds,counts.refunds+' refund, case, dispute or chargeback events');
    setCard('Mapping review',counts.mapping,counts.mapping+' carrier mappings need review');
    var risk=counts.overdue+counts.returns+counts.replacements+counts.refunds;
    var base=Math.max(1,counts.total+counts.returns);var score=Math.max(0,Math.min(100,Math.round(100*(base-risk)/base)));
    var ring=document.querySelector('.fbm-score-ring');if(ring){ring.style.setProperty('--fbm-score',score+'%');var strong=ring.querySelector('strong');if(strong)strong.textContent=score+'%';}
    var head=document.querySelector('.fbm-period-head .small.text-muted');if(head)head.textContent=b.label+' · DB-backed shipping and lifecycle facts';
    var guide=document.querySelector('.fbm-guide-period');if(guide){var strong=guide.querySelector('strong'),span=guide.querySelector('span');if(strong)strong.textContent=b.label;if(span)span.textContent=counts.total+' FBM orders';}
  }
  rangeInput.addEventListener('change',syncHealth);
  if(fromInput)fromInput.addEventListener('change',syncHealth);
  if(toInput)toInput.addEventListener('change',syncHealth);
  form.addEventListener('submit',syncHealth);
  syncHealth();
})();
</script>'''


def install_governed_fbm_browser_session_authority_alignment(app) -> None:
    if getattr(app, "_bt38_fbm_browser_session_authority_alignment_installed", False):
        return

    # Final authority after the older dispatch/history wrappers: one rendered
    # one-year persisted working set, then browser-local History/lifecycle/pager.
    page._latest_distinct_fbm_rows = _browser_session_rows

    if not hasattr(dispatch, "_bt38_original_presentation"):
        dispatch._bt38_original_presentation = dispatch._presentation
    dispatch._presentation = _session_presentation

    if not hasattr(dispatch, "_bt38_original_inject"):
        dispatch._bt38_original_inject = dispatch._inject

    def aligned_inject(html, payload, fba_count):
        rendered = dispatch._bt38_original_inject(html, payload, fba_count)
        script = _session_health_script()
        return rendered.replace("</body>", script + "</body>", 1) if "</body>" in rendered else rendered + script

    dispatch._inject = aligned_inject
    app._bt38_fbm_browser_session_authority_alignment_installed = True
    app.logger.info(
        "BT38 FBM final browser-session authority aligned: History + Health + lifecycle move together; bottom pager remains separate; no marketplace/provider reads"
    )
