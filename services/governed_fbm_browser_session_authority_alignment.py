"""Keep FBM History, lifecycle counts and Health on one browser-session snapshot.

The selected FBM History window is loaded once through the canonical History
snapshot reader. History/lifecycle/Health/search/pager then operate over the same
rendered browser-session facts. The bottom pager remains presentation-only.

No marketplace/provider read, write, polling, timer, EventSource or fetch path is
introduced by this module.
"""
from __future__ import annotations

from services import governed_fbm_dispatch_queue_alignment as dispatch
from services import governed_fbm_page_alignment as page
from services.fbm_shipping_state import shipment_confirmation_state



def _bounded_browser_session_rows(limit: int):
    """Load one bounded History working set; lifecycle/search/pager stay browser-local."""
    from services import governed_fbm_global_search_alignment as global_search
    rows, truncated = global_search._session_snapshot_rows()
    # The browser owns lifecycle/search/pager presentation over this one History set.
    # A stale fbm_tab URL must not narrow or reload the server-side working set.
    return rows, bool(truncated)


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
    """Project Health from the already-rendered FBM session; never read another authority."""
    return r"""
<script id="bt38FbmSessionHealthProjection">
(function(){
  function setCard(label,value){
    document.querySelectorAll('.fbm-period-card').forEach(function(card){
      var node=card.querySelector('.fbm-period-label');
      if(node&&String(node.textContent||'').trim()===label){
        var valueNode=card.querySelector('.fbm-period-value');
        if(valueNode)valueNode.textContent=String(Number(value||0));
      }
    });
  }
  function project(){
    var rows=Array.from(document.querySelectorAll('tr.fbm-order-row'));
    var visible=rows.filter(function(row){return row.dataset.fbmHistoryMatch!=='0';});
    var counts={ready_dispatch:0,pending:0,dispatched:0,cancelled:0,replacements:0,refunds:0};
    var platforms={};
    var awaiting=0,mapping=0,returns=0;
    visible.forEach(function(row){
      var q=String(row.dataset.fbmQueue||'');
      if(Object.prototype.hasOwnProperty.call(counts,q))counts[q]+=1;
      var platform=String(row.dataset.fbmPlatform||'').trim();
      if(platform)platforms[platform]=(platforms[platform]||0)+1;
      if(String(row.dataset.fbmMappingReview||'')==='1')mapping+=1;
      if(String(row.dataset.fbmReturnEvent||'')==='1')returns+=1;
      var state=String(row.dataset.fbmShipmentState||'').toLowerCase();
      if(state==='label_purchased'||state==='marketplace_confirmed')awaiting+=1;
    });
    var ready=counts.ready_dispatch;
    var refunds=counts.refunds;
    var replacements=counts.replacements;
    var risk=mapping+returns+replacements+refunds;
    var base=Math.max(1,visible.length+returns+replacements+refunds);
    var score=Math.max(0,Math.min(100,Math.round(100*(base-risk)/base)));
    setCard('Orders',visible.length);
    setCard('Ready to ship',ready);
    setCard('Dispatched',counts.dispatched);
    setCard('Awaiting carrier',awaiting);
    setCard('Returns',returns);
    setCard('Replacements',replacements);
    setCard('Refunds / issues',refunds);
    setCard('Mapping review',mapping);
    var period=document.querySelector('.fbm-guide-period span');
    if(period)period.textContent=String(visible.length)+' FBM orders';
    var ring=document.querySelector('.fbm-score-ring');
    if(ring){ring.style.setProperty('--fbm-score',String(score)+'%');var strong=ring.querySelector('strong');if(strong)strong.textContent=String(score)+'%';}
    var riskNode=document.querySelector('.fbm-score-card .small.text-muted');
    if(riskNode)riskNode.textContent=String(risk)+' risk/issue actions in this period';
  }
  document.addEventListener('bt38-fbm-session-rendered',project);
  document.addEventListener('bt38-fbm-committed-snapshot-applied',function(){queueMicrotask(project);});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',function(){queueMicrotask(project);},{once:true});else queueMicrotask(project);
})();
</script>
""




def install_governed_fbm_browser_session_authority_alignment(app) -> None:
    if getattr(app, "_bt38_fbm_browser_session_authority_alignment_installed", False):
        return

    # History is the one server-loaded FBM working set. Lifecycle/search/pager
    # remain browser-local over that exact set.
    page._latest_distinct_fbm_rows = _bounded_browser_session_rows

    page._health_summary = _browser_session_health_shell

    if not hasattr(dispatch, "_bt38_original_presentation"):
        dispatch._bt38_original_presentation = dispatch._presentation
    dispatch._presentation = _session_presentation

    if not hasattr(dispatch, "_bt38_original_inject"):
        dispatch._bt38_original_inject = dispatch._inject
    def aligned_inject(html, payload, fba_count):
        aligned = dispatch._bt38_original_inject(html, payload, fba_count)
        script = _session_health_script()
        marker = "</body>"
        return aligned.replace(marker, script + marker, 1) if script and marker in aligned else aligned + script
    dispatch._inject = aligned_inject
    app._bt38_fbm_browser_session_authority_alignment_installed = True
    app.logger.info("BT38 FBM browser-session authority aligned: one selected-History working set; Health/lifecycle/search/pager use rendered session facts; exact-record events preserved")