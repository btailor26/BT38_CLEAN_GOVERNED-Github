"""Expose unresolved truth-risk areas without manufacturing replacement facts.

This is a presentation + audit-request layer only.  It does not correct, infer,
recalculate or overwrite marketplace, warehouse, shipment or financial truth.
When BT38 knows an area still contains fallback/default behaviour, the UI shows
an explicit red "Needs admin attention" warning.  A user may request review;
that request is recorded in the existing SystemEvent audit stream.

No marketplace/provider read or write, no inventory mutation, no worker, no
poller, no new truth table and no second order/shipment authority are created.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from html import escape
from typing import Any

from flask import jsonify, request
from flask_login import current_user, login_required

from extensions import db
from models import SystemEvent


_REVIEW_CATEGORY = "admin_truth_review_request"
_ROUTE = "/governed/actions/admin-truth-review-request"


_FBM_RISKS = (
    (
        "Marketplace order quantity",
        "quantity",
        "Current import paths can still apply a fallback quantity when provider quantity is missing or invalid. Treat uncertain quantity as needing review until the provider truth is proven.",
    ),
    (
        "SKU / item identity",
        "sku_item_identity",
        "Current import paths can still use fallback identifiers when provider SKU or item identity is incomplete. A fallback identifier must not be treated as provider truth.",
    ),
    (
        "Shipment timestamp",
        "shipment_timestamp",
        "Some existing paths can derive a shipped time from another timestamp. Carrier or marketplace shipment time must be proven before it is treated as truth.",
    ),
    (
        "Destination / parcel facts",
        "destination_parcel",
        "Missing destination, quantity, weight or parcel facts must remain unknown or require review. They must not be silently replaced by plausible defaults.",
    ),
)

_MCF_RISKS = (
    (
        "MCF order quantity / items",
        "mcf_quantity_items",
        "Every marketplace line and quantity must come from the source order. Missing item or quantity truth must be reviewed rather than defaulted.",
    ),
    (
        "MCF destination",
        "mcf_destination",
        "Customer name, address and country sent to Amazon must be source-order truth. Missing destination facts must be flagged instead of invented.",
    ),
    (
        "MCF declared value",
        "mcf_declared_value",
        "Declared value and product money must come from confirmed order evidence. Missing values must not be silently sent as zero.",
    ),
    (
        "MCF actual charges",
        "mcf_actual_charges",
        "BT38 estimates are a controlled layer only. Actual MCF cost remains unknown until Amazon supplies exact order-specific financial evidence.",
    ),
)


def _clean(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _entity_id(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _recent_duplicate(
    *,
    actor_id: int | None,
    entity_type: str,
    entity_id: int | None,
    section: str,
    field: str,
    reason: str,
) -> SystemEvent | None:
    cutoff = datetime.utcnow() - timedelta(minutes=5)
    query = (
        SystemEvent.query
        .filter(SystemEvent.category == _REVIEW_CATEGORY)
        .filter(SystemEvent.timestamp >= cutoff)
        .filter(SystemEvent.actor_id == actor_id)
        .filter(SystemEvent.entity_type == (entity_type or None))
    )
    if entity_id is None:
        query = query.filter(SystemEvent.entity_id.is_(None))
    else:
        query = query.filter(SystemEvent.entity_id == entity_id)

    for event in query.order_by(SystemEvent.id.desc()).limit(20).all():
        details = dict(event.details_json or {})
        if (
            details.get("section") == section
            and details.get("field") == field
            and details.get("reason") == reason
        ):
            return event
    return None


@login_required
def request_admin_truth_review():
    """Record a review request only; never alter the underlying business fact."""
    payload = request.get_json(silent=True) or {}
    section = _clean(payload.get("section"), 120)
    field = _clean(payload.get("field"), 120)
    reason = _clean(payload.get("reason"), 1000)
    source_page = _clean(payload.get("source_page"), 240)
    current_value = _clean(payload.get("current_value"), 500)
    entity_type = _clean(payload.get("entity_type"), 50) or "truth_review"
    entity_id = _entity_id(payload.get("entity_id"))

    if not section or not reason:
        return jsonify({
            "success": False,
            "reason": "section_and_reason_required",
        }), 400

    actor_id = _entity_id(getattr(current_user, "id", None))
    duplicate = _recent_duplicate(
        actor_id=actor_id,
        entity_type=entity_type,
        entity_id=entity_id,
        section=section,
        field=field,
        reason=reason,
    )
    if duplicate is not None:
        return jsonify({
            "success": True,
            "requested": True,
            "duplicate": True,
            "event_id": int(duplicate.id),
        })

    event = SystemEvent(
        actor="admin" if str(getattr(current_user, "role", "")).lower() == "admin" else "user",
        actor_id=actor_id,
        category=_REVIEW_CATEGORY,
        entity_id=entity_id,
        entity_type=entity_type,
        description=f"Needs admin attention: {section}",
        details_json={
            "section": section,
            "field": field or None,
            "reason": reason,
            "source_page": source_page or request.referrer or request.path,
            "current_value": current_value or None,
            "requested_by_username": _clean(getattr(current_user, "username", None), 120) or None,
            "requested_by_email": _clean(getattr(current_user, "email", None), 200) or None,
            "truth_mutation_started": False,
            "marketplace_write_started": False,
            "provider_write_started": False,
            "inventory_mutation_started": False,
        },
    )
    db.session.add(event)
    db.session.commit()

    return jsonify({
        "success": True,
        "requested": True,
        "duplicate": False,
        "event_id": int(event.id),
    })


def _risk_chip(section: str, field: str, reason: str, *, page_key: str) -> str:
    return (
        '<span class="bt38-truth-warning" tabindex="0" '
        f'data-bt38-section="{escape(section, quote=True)}" '
        f'data-bt38-field="{escape(field, quote=True)}" '
        f'data-bt38-reason="{escape(reason, quote=True)}" '
        f'data-bt38-page="{escape(page_key, quote=True)}">'
        '<span class="bt38-truth-warning-icon" aria-hidden="true">&#9888;</span>'
        f'<span class="bt38-truth-warning-label">{escape(section)}</span>'
        '<span class="bt38-truth-warning-box" role="note">'
        '<strong>Needs admin attention</strong>'
        f'<span class="bt38-truth-warning-copy">{escape(reason)}</span>'
        '<label class="bt38-truth-review-check">'
        '<input type="checkbox" class="form-check-input bt38-truth-review-request"> '
        '<span>Request admin review</span>'
        '</label>'
        '<span class="bt38-truth-review-status" aria-live="polite"></span>'
        '</span>'
        '</span>'
    )


def _panel(page_key: str, risks: tuple[tuple[str, str, str], ...]) -> str:
    chips = "".join(
        _risk_chip(section, field, reason, page_key=page_key)
        for section, field, reason in risks
    )
    return (
        '<div class="bt38-truth-attention-panel" data-bt38-truth-attention="1">'
        '<div class="bt38-truth-attention-title">'
        '<span class="bt38-truth-attention-main">&#9888; Data truth review</span>'
        '<span class="bt38-truth-attention-sub">BT38 is explicitly marking unresolved areas instead of treating defaults as verified facts.</span>'
        '</div>'
        f'<div class="bt38-truth-attention-items">{chips}</div>'
        '</div>'
    )


def _assets() -> str:
    return r'''
<style id="bt38-truth-attention-style">
.bt38-truth-attention-panel{border:1px solid #dc3545;border-left:4px solid #dc3545;background:#fff5f5;border-radius:.45rem;padding:.55rem .7rem;margin:0 0 .7rem 0;position:relative;z-index:20}
.bt38-truth-attention-title{display:flex;align-items:baseline;gap:.65rem;flex-wrap:wrap;margin-bottom:.35rem}.bt38-truth-attention-main{color:#b02a37;font-weight:700;font-size:.82rem}.bt38-truth-attention-sub{color:#6c757d;font-size:.72rem}
.bt38-truth-attention-items{display:flex;gap:.4rem;flex-wrap:wrap}.bt38-truth-warning{position:relative;display:inline-flex;align-items:center;gap:.28rem;border:1px solid #dc3545;background:#fff;color:#b02a37;border-radius:999px;padding:.18rem .48rem;font-size:.7rem;font-weight:600;cursor:help;outline:none}.bt38-truth-warning-icon{font-size:.82rem;line-height:1}.bt38-truth-warning-label{white-space:nowrap}
.bt38-truth-warning-box{display:none;position:absolute;left:0;top:calc(100% + 6px);z-index:10000;width:min(360px,80vw);background:#fff;color:#212529;border:1px solid #dc3545;border-radius:.45rem;box-shadow:0 .45rem 1.2rem rgba(0,0,0,.16);padding:.65rem;font-weight:400;font-size:.76rem;line-height:1.35}.bt38-truth-warning:hover .bt38-truth-warning-box,.bt38-truth-warning:focus-within .bt38-truth-warning-box,.bt38-truth-warning:focus .bt38-truth-warning-box{display:block}.bt38-truth-warning-box strong{display:block;color:#b02a37;margin-bottom:.25rem}.bt38-truth-warning-copy{display:block;margin-bottom:.5rem}.bt38-truth-review-check{display:flex;gap:.4rem;align-items:center;font-weight:600;cursor:pointer;margin:0}.bt38-truth-review-status{display:block;margin-top:.35rem;font-size:.7rem}.bt38-truth-review-status.is-ok{color:#198754}.bt38-truth-review-status.is-error{color:#dc3545}
.bt38-row-truth-warning{margin-left:.35rem;vertical-align:middle}.bt38-row-truth-warning .bt38-truth-warning-label{display:none}.bt38-row-truth-warning .bt38-truth-warning-icon{font-size:.9rem}
</style>
<script id="bt38-truth-attention-script">
(function(){
  if(window.__bt38TruthAttentionInstalled){return;}
  window.__bt38TruthAttentionInstalled=true;

  function csrf(){
    var node=document.querySelector('meta[name="csrf-token"]');
    return node ? String(node.getAttribute('content')||'') : '';
  }
  function addRowWarning(target, section, field, reason, row){
    if(!target || target.querySelector('[data-bt38-row-field="'+field+'"]')){return;}
    var wrap=document.createElement('span');
    wrap.className='bt38-truth-warning bt38-row-truth-warning';
    wrap.tabIndex=0;
    wrap.setAttribute('data-bt38-row-field',field);
    wrap.setAttribute('data-bt38-section',section);
    wrap.setAttribute('data-bt38-field',field);
    wrap.setAttribute('data-bt38-reason',reason);
    wrap.setAttribute('data-bt38-page',window.location.pathname);
    wrap.setAttribute('data-bt38-entity-type','marketplace_order');
    wrap.setAttribute('data-bt38-entity-id',row && row.dataset ? (row.dataset.orderId||'') : '');
    wrap.innerHTML='<span class="bt38-truth-warning-icon" aria-hidden="true">&#9888;</span><span class="bt38-truth-warning-label">'+section+'</span><span class="bt38-truth-warning-box" role="note"><strong>Needs admin attention</strong><span class="bt38-truth-warning-copy"></span><label class="bt38-truth-review-check"><input type="checkbox" class="form-check-input bt38-truth-review-request"> <span>Request admin review</span></label><span class="bt38-truth-review-status" aria-live="polite"></span></span>';
    wrap.querySelector('.bt38-truth-warning-copy').textContent=reason;
    target.appendChild(wrap);
  }
  function markObviousUnknowns(){
    document.querySelectorAll('.fbm-order-row').forEach(function(row){
      var cells=row.querySelectorAll('td');
      if(cells.length<8){return;}
      var qty=(cells[4].textContent||'').trim();
      if(!qty || qty==='0' || qty==='—'){
        addRowWarning(cells[4],'Order quantity','quantity','Quantity is missing or not proven. BT38 must not assume a unit count.',row);
      }
      var code=cells[3].querySelector('code');
      var sku=code ? (code.textContent||'').trim() : '';
      if(!sku || sku==='—'){
        addRowWarning(cells[3],'SKU / item identity','sku_item_identity','SKU or marketplace item identity is incomplete. Treat this line as unresolved until source evidence is confirmed.',row);
      }
      var shipmentText=(cells[7].textContent||'').toLowerCase();
      if(shipmentText.indexOf('marketplace says shipped')>=0 && shipmentText.indexOf('parcel id pending')<0 && !cells[7].querySelector('code')){
        addRowWarning(cells[7],'Shipment evidence','shipment_tracking','Marketplace lifecycle says shipped but parcel tracking evidence is not present on this row.',row);
      }
      if((row.textContent||'').toLowerCase().indexOf('mapping review')>=0){
        addRowWarning(cells[7],'Parcel mapping','parcel_mapping','Parcel facts are under review. BT38 must not invent dimensions or packing truth.',row);
      }
      if(row.hasAttribute('data-fbm-mcf-readonly') && (row.textContent||'').toLowerCase().indexOf('amazon order id pending')>=0){
        addRowWarning(cells[2],'MCF Amazon order identity','mcf_amazon_order_identity','Amazon order identity has not yet been confirmed for this MCF order.',row);
      }
    });
  }
  async function submitReview(input){
    var root=input.closest('.bt38-truth-warning');
    if(!root){return;}
    var status=root.querySelector('.bt38-truth-review-status');
    input.disabled=true;
    if(status){status.className='bt38-truth-review-status';status.textContent='Sending review request…';}
    var body={
      section:root.dataset.bt38Section||'',
      field:root.dataset.bt38Field||'',
      reason:root.dataset.bt38Reason||'',
      source_page:root.dataset.bt38Page||window.location.pathname,
      entity_type:root.dataset.bt38EntityType||'truth_review',
      entity_id:root.dataset.bt38EntityId||null,
      current_value:root.dataset.bt38CurrentValue||null
    };
    try{
      var headers={'Content-Type':'application/json'};
      var token=csrf();
      if(token){headers['X-CSRFToken']=token;headers['X-CSRF-Token']=token;}
      var response=await fetch('/governed/actions/admin-truth-review-request',{method:'POST',headers:headers,credentials:'same-origin',body:JSON.stringify(body)});
      var data=await response.json().catch(function(){return {};});
      if(!response.ok || !data.success){throw new Error(data.reason||('HTTP '+response.status));}
      if(status){status.className='bt38-truth-review-status is-ok';status.textContent=data.duplicate?'Admin review already requested.':'Admin review requested.';}
      input.checked=true;
    }catch(error){
      input.disabled=false;
      input.checked=false;
      if(status){status.className='bt38-truth-review-status is-error';status.textContent='Request not sent: '+String(error && error.message || error);}
    }
  }
  document.addEventListener('change',function(event){
    var input=event.target.closest && event.target.closest('.bt38-truth-review-request');
    if(input && input.checked){submitReview(input);}
  });
  markObviousUnknowns();
  if(window.feather && typeof window.feather.replace==='function'){window.feather.replace();}
})();
</script>
'''


def _inject_truth_attention(html: str, *, path: str) -> str:
    if 'data-bt38-truth-attention="1"' in html:
        return html

    path_key = str(path or "").lower()
    if path_key.startswith("/fbm"):
        risks = _FBM_RISKS
        page_key = "fbm"
    elif "mcf" in path_key:
        risks = _MCF_RISKS
        page_key = "mcf"
    else:
        return html

    panel = _panel(page_key, risks)
    first_card = html.find('<div class="card')
    if first_card >= 0:
        html = html[:first_card] + panel + html[first_card:]
    else:
        body_end = html.rfind("</body>")
        html = html[:body_end] + panel + html[body_end:] if body_end >= 0 else panel + html

    body_end = html.rfind("</body>")
    assets = _assets()
    return html[:body_end] + assets + html[body_end:] if body_end >= 0 else html + assets


def _install() -> None:
    from app import app

    endpoint = "bt38_admin_truth_review_request"
    if endpoint not in app.view_functions:
        app.add_url_rule(
            _ROUTE,
            endpoint=endpoint,
            view_func=request_admin_truth_review,
            methods=["POST"],
        )

    if getattr(app, "_bt38_truth_attention_after_request", False):
        return

    @app.after_request
    def bt38_truth_attention_after_request(response):
        try:
            content_type = str(response.content_type or "").lower()
            if response.status_code == 200 and "text/html" in content_type:
                path = str(request.path or "")
                if path.startswith("/fbm") or "mcf" in path.lower():
                    html = response.get_data(as_text=True)
                    rendered = _inject_truth_attention(html, path=path)
                    if rendered != html:
                        response.set_data(rendered)
                        response.headers["Content-Length"] = str(len(response.get_data()))
        except Exception:
            # A warning overlay must never prevent the canonical page from loading.
            pass
        return response

    app._bt38_truth_attention_after_request = True


_install()
