"""Keep FBM History, lifecycle counts and Health on one browser-session snapshot.

The initial /fbm read is explicitly bound to the canonical bounded page-reader
contract even though older dispatch alignment replaces the module attribute
before this installer runs. History/lifecycle/Health then operate over the
rendered browser-session facts. The bottom pager remains presentation-only.

No marketplace/provider read, write, polling, timer, EventSource or fetch path is
introduced by this module.
"""
from __future__ import annotations

from services import governed_fbm_dispatch_queue_alignment as dispatch
from services import governed_fbm_page_alignment as page
from services.fbm_shipping_state import shipment_confirmation_state


_LIFECYCLE_SESSION_LIMIT = 300


def _canonical_bounded_page_rows(limit: int):
    """Use the original page reader contract without the dispatch broad-read override."""
    eligible = (
        page.func.upper(page.func.coalesce(page.MarketplaceOrder.fulfillment_type, "")).notin_(("FBA", "AFN", "MCF")),
        ~page.func.lower(page.func.coalesce(page.MarketplaceOrder.status, "")).like("mcf_%"),
    )
    query = page.db.session.query(page.MarketplaceOrder).filter(*eligible)
    platform_filter = str(page.request.args.get("platform") or "").strip().lower()
    status_filter = str(page.request.args.get("status") or "").strip().lower()
    if platform_filter:
        query = query.filter(page.MarketplaceOrder.store.has(platform=platform_filter))
    tracking_present = page.MarketplaceOrder.tracking_number.isnot(None) & (page.MarketplaceOrder.tracking_number != "")
    if status_filter == "tracking recorded":
        query = query.filter(tracking_present)
    elif status_filter == "dispatched":
        query = query.filter(~tracking_present, page.MarketplaceOrder.shipped_at.isnot(None))
    elif status_filter == "ready for fbm routing":
        query = query.filter(~tracking_present, page.MarketplaceOrder.shipped_at.is_(None))
    candidate_limit = min(
        page._FBM_MAX_EXPANDED * page._FBM_DISCOVERY_MULTIPLIER,
        max(limit + 1, (limit + 1) * page._FBM_DISCOVERY_MULTIPLIER),
    )
    candidates = (
        query.options(page.joinedload(page.MarketplaceOrder.store))
        .order_by(page.MarketplaceOrder.id.desc())
        .limit(candidate_limit)
        .all()
    )
    rows = []
    seen = set()
    for row in candidates:
        if row.store_id is None or not row.marketplace_order_id:
            continue
        key = (int(row.store_id), str(row.marketplace_order_id))
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
        if len(rows) >= limit + 1:
            break
    rows.sort(key=lambda row: (row.created_at is not None, row.created_at, row.id), reverse=True)
    has_more = len(rows) > limit or len(candidates) == candidate_limit
    return rows[:limit], has_more


def _bounded_browser_session_rows(limit: int):
    """Build one bounded lifecycle session, then let the browser page it locally."""
    session_limit = max(int(limit or 0), _LIFECYCLE_SESSION_LIMIT)
    rows, has_more = page._bt38_original_bounded_fbm_rows(session_limit)
    return rows, has_more


def _session_presentation(rows):
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


def _browser_session_health_shell() -> dict:
    from services import governed_fbm_all_orders_health_alignment as health
    mode, start_at, end_at, label, raw_from, raw_to = health._selected_history_window()
    return {
        "period_mode": mode, "period_label": label, "period_start": start_at, "period_end": end_at,
        "range_from": raw_from, "range_to": raw_to, "total": 0, "ready": 0, "dispatch_due": 0,
        "dispatched": 0, "awaiting_acceptance": 0, "overdue": 0, "mapping_review": 0, "returns": 0,
        "replacements": 0, "refund_issues": 0, "platform_counts": {}, "health_score": 100,
        "risk_actions": 0, "shipping_actions": 0, "truncated": False, "source": "browser_session",
    }


def _session_health_script() -> str:
    return r'''<script id="bt38FbmBrowserSessionHealthAuthority">
(function(){
  var form=document.getElementById('bt38FbmControls')||document.getElementById('bt38FbmHistoryControls');
  var rangeInput=document.getElementById('bt38FbmRangeSelect')||document.getElementById('bt38FbmRange');
  var fromInput=form&&form.querySelector('[name="fbm_from"]');
  var toInput=form&&form.querySelector('[name="fbm_to"]');
  var dataNode=document.getElementById('bt38FbmLifecycleTabsData');
  var table=document.querySelector('.fbm-orders-table');
  if(!form||!rangeInput||!dataNode||!table)return;
  var data={};try{data=JSON.parse(dataNode.textContent||'{}')}catch(e){return;}
  form.onsubmit=function(event){if(event)event.preventDefault();syncHealth();return false;};
  rangeInput.onchange=null;
  function currentSession(){var fallback={tab:'pending',search:'',range:'3d',from:'',to:'',dirty:false};return (window.BT38&&typeof window.BT38.getPageSession==='function')?window.BT38.getPageSession('fbm',fallback):fallback;}
  function bounds(){var saved=currentSession()||{};var range=String(saved.range||rangeInput.value||'3d').toLowerCase();var from=String(saved.from||(fromInput&&fromInput.value)||'');var to=String(saved.to||(toInput&&toInput.value)||'');var today=new Date();today=new Date(today.getFullYear(),today.getMonth(),today.getDate());if(range==='custom')return {range:range,start:from?new Date(from+'T00:00:00'):null,end:to?new Date(to+'T23:59:59'):null,label:(from&&to)?from+' – '+to:'Custom'};var days={'3d':3,'7d':7,'30d':30,'90d':90,'1y':365}[range]||3;var start=new Date(today);start.setDate(start.getDate()-(days-1));var end=new Date(today);end.setHours(23,59,59,999);var labels={'3d':'Last 3 days','7d':'Last 7 days','30d':'Last 30 days','90d':'Last 90 days','1y':'Last year'};return {range:range,start:start,end:end,label:labels[range]||'Last 3 days'};}
  function included(info,b){if(!info||!info.created_at)return false;var d=new Date(info.created_at);if(isNaN(d.getTime()))return false;if(b.start&&d<b.start)return false;if(b.end&&d>b.end)return false;return true;}
  function setCard(label,value,tip){document.querySelectorAll('.fbm-period-card').forEach(function(card){var name=card.querySelector('.fbm-period-label');if(!name||name.textContent.trim()!==label)return;var number=card.querySelector('.fbm-period-value');if(number)number.textContent=String(value);var help=card.querySelector('.fbm-period-tip');if(help&&tip)help.innerHTML='<div>'+tip+'</div>';});}
  function syncHealth(){var b=bounds();var counts={total:0,ready:0,dispatched:0,awaiting:0,overdue:0,returns:0,replacements:0,refunds:0,mapping:0};Object.keys(data).forEach(function(id){var info=data[id];if(!included(info,b))return;counts.total+=1;if(info.queue==='ready_dispatch')counts.ready+=1;if(info.queue==='dispatched')counts.dispatched+=1;if(info.queue==='replacements')counts.replacements+=1;if(info.queue==='refunds')counts.refunds+=1;if(info.shipment_state==='awaiting_carrier_acceptance')counts.awaiting+=1;if(info.shipment_state==='acceptance_overdue')counts.overdue+=1;if(info.return_event)counts.returns+=1;if(info.mapping_review)counts.mapping+=1;});setCard('Orders',counts.total,counts.total+' FBM orders in this History period');setCard('Ready to ship',counts.ready,counts.ready+' orders still need a shipping action');setCard('Dispatched',counts.dispatched,counts.dispatched+' orders have dispatch/tracking recorded');setCard('Awaiting carrier',counts.awaiting,counts.awaiting+' labels are waiting for carrier acceptance');setCard('Carrier overdue',counts.overdue,counts.overdue+' shipments are overdue for carrier acceptance');setCard('Returns',counts.returns,counts.returns+' return events recorded in this period');setCard('Replacements',counts.replacements,counts.replacements+' replacement events recorded in this period');setCard('Refunds / issues',counts.refunds,counts.refunds+' refund, case, dispute or chargeback events');setCard('Mapping review',counts.mapping,counts.mapping+' carrier mappings need review');var risk=counts.overdue+counts.returns+counts.replacements+counts.refunds;var base=Math.max(1,counts.total+counts.returns);var score=Math.max(0,Math.min(100,Math.round(100*(base-risk)/base)));var ring=document.querySelector('.fbm-score-ring');if(ring){ring.style.setProperty('--fbm-score',score+'%');var strong=ring.querySelector('strong');if(strong)strong.textContent=score+'%';}var head=document.querySelector('.fbm-period-head .small.text-muted');if(head)head.textContent=b.label+' · committed FBM session facts';var guide=document.querySelector('.fbm-guide-period');if(guide){var strong2=guide.querySelector('strong'),span=guide.querySelector('span');if(strong2)strong2.textContent=b.label;if(span)span.textContent=counts.total+' FBM orders';}}
  rangeInput.addEventListener('change',syncHealth);if(fromInput)fromInput.addEventListener('change',syncHealth);if(toInput)toInput.addEventListener('change',syncHealth);form.addEventListener('submit',syncHealth);document.addEventListener('bt38-fbm-committed-snapshot-applied',syncHealth);syncHealth();
})();
</script>'''


def install_governed_fbm_browser_session_authority_alignment(app) -> None:
    if getattr(app, "_bt38_fbm_browser_session_authority_alignment_installed", False):
        return

    # Dispatch alignment has already replaced the module attribute at this point.
    # Bind the browser session to the canonical bounded page contract explicitly;
    # never capture dispatch._complete_fbm_page_rows as the "bounded" reader.
    page._bt38_original_bounded_fbm_rows = _canonical_bounded_page_rows
    page._latest_distinct_fbm_rows = _bounded_browser_session_rows

    page._health_summary = _browser_session_health_shell

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
    app.logger.info("BT38 FBM browser-session authority aligned: canonical bounded initial read; dispatch broad-read override bypassed; Health/lifecycle use rendered session facts; exact-record events preserved")