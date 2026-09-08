"""Presentation-only alignment for governed FBM UI.

The marketplace/provider handoff owns collection and persistence. Page GETs must
not recover, reconcile, hydrate, or call marketplace/provider APIs. This module
keeps presentation cleanup separate while installing the existing DB-first
marketplace lifecycle alignment before the FBM page wrapper is bound.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from html import escape
import json
import re
from typing import Any
from zoneinfo import ZoneInfo

from flask import jsonify, request
from flask_login import login_required
from sqlalchemy import tuple_

_JOURNEY_LABEL_REPLACEMENTS = (("1 · Picked up", "Picked up"), ("2 · In transit", "In transit"), ("3 · Delivered", "Delivered"))
_TRACKING_LINK_STYLE = ('<style id="bt38FbmTrackingLinkAlignment">''.fbm-orders-table td a:has(code),.fbm-orders-table td a:has(code):hover,.fbm-orders-table td a:has(code):focus,.fbm-orders-table .fbm-tracking-journey,.fbm-orders-table .fbm-tracking-journey:hover,.fbm-orders-table .fbm-tracking-journey:focus{text-decoration:none!important;border-bottom:0!important;box-shadow:none!important}.fbm-orders-table td a:has(code) code,.fbm-orders-table .fbm-tracking-journey code{text-decoration:none!important;border-bottom:0!important;box-shadow:none!important}</style>')
_MARKETPLACE_BADGE_STYLE = ('<style id="bt38FbmMarketplaceBadgeAlignment">''.fbm-marketplace-cell{min-width:110px!important}.fbm-marketplace-logo{display:block!important;max-width:82px!important;max-height:36px!important;width:auto!important;height:auto!important;object-fit:contain!important;object-position:left center!important;image-rendering:auto}.bt38-inline-shipping{min-width:190px}.bt38-inline-shipping .btn{white-space:nowrap}.bt38-inline-shipping select,.bt38-inline-shipping input{max-width:220px}</style>')
_PROMISE_JOURNEY_SCRIPT = '<script id="bt38FbmPromiseJourneyAlignment" src="/static/js/fbm_delivery_promise_journey_alignment.js"></script>'
_EVENT_SESSION_REFRESH_SCRIPT = '<script id="bt38FbmEventSessionRefreshAlignment" src="/static/js/fbm_event_session_refresh_alignment.js"></script>'
_SCROLL_POSITION_SCRIPT = '<script id="bt38FbmScrollPositionAlignment" src="/static/js/fbm_scroll_position_alignment.js"></script>'
_INLINE_SHIPPING_SCRIPT = r'''<script id="bt38FbmInlineShippingAlignment">
(function(){
'use strict';
async function jsonPost(url, body){const r=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify(body||{})});const p=await r.json().catch(()=>({}));if(!r.ok||p.success===false)throw new Error(p.message||('HTTP '+r.status));return p;}
function rowFor(el){return el&&el.closest('.fbm-order-row');}
document.addEventListener('click',async function(e){
  const rates=e.target.closest('.bt38-get-saved-rates');
  if(rates){e.preventDefault();e.stopPropagation();const row=rowFor(rates);if(!row)return;let parcel={};try{parcel=JSON.parse(rates.dataset.parcel||'{}');}catch(_){parcel={};}rates.disabled=true;rates.textContent='Getting rates…';try{await jsonPost('/fbm/orders/'+encodeURIComponent(rates.dataset.orderId)+'/packlink/rates',{parcel:parcel});location.reload();}catch(err){rates.disabled=false;rates.textContent='Get rates';alert(err.message);}return;}
  const save=e.target.closest('.bt38-save-cutoff');
  if(save){e.preventDefault();e.stopPropagation();const row=rowFor(save);const select=row&&row.querySelector('.bt38-cutoff-service');const time=row&&row.querySelector('.bt38-cutoff-time');if(!select||!select.value||!time||!time.value){alert('Choose the carrier/service and enter the actual cutoff time.');return;}let item={};try{item=JSON.parse(select.value);}catch(_){item={};}if(!item.carrier||!item.service)return;save.disabled=true;try{await jsonPost('/fbm/carrier-cutoff',{provider:'packlink',carrier:item.carrier,service:item.service,cutoff_time:time.value});location.reload();}catch(err){save.disabled=false;alert(err.message);}return;}
  const prepare=e.target.closest('.bt38-prepare-recommended-label');
  if(prepare){e.preventDefault();e.stopPropagation();prepare.disabled=true;prepare.textContent='Preparing…';try{const p=await jsonPost('/fbm/orders/'+encodeURIComponent(prepare.dataset.orderId)+'/packlink/draft',{quote_id:Number(prepare.dataset.quoteId),rate_id:prepare.dataset.rateId,confirm_create:'CREATE_PACKLINK_DRAFT'});const cell=prepare.closest('.bt38-inline-shipping');if(cell)cell.innerHTML='<div class="small text-muted">Recommended shipping</div><strong>'+String(prepare.dataset.carrier||'Packlink')+'</strong><div class="small text-warning mt-1">Payment required before the label is assigned or printable.</div><a class="btn btn-sm btn-success mt-1" href="https://pro.packlink.com/" target="_blank" rel="noopener">Pay in Packlink</a><button class="btn btn-sm btn-outline-primary mt-1 packlink-existing-status" type="button" data-shipment-id="'+p.shipment_id+'">Check payment / label</button>'; }catch(err){prepare.disabled=false;prepare.textContent='Prepare label';alert(err.message);}return;}
},true);
})();
</script>'''

_FBM_ROW_RE = re.compile(r'(<tr class="fbm-order-row" data-order-id="(?P<row_id>\d+)"[^>]*>)(?P<body>.*?)(</tr>)', re.DOTALL)
_SHIPPING_CELL_RE = re.compile(r'<td class="fbm-route-cell">(?P<body>.*?)</td>', re.DOTALL)
_MARKETPLACE_PROMISE_SERVICE_RE = re.compile(r'<div class="small text-muted">Marketplace promise</div><strong>(?P<service>.*?)</strong>', re.DOTALL)
_DELIVER_BY_RE = re.compile(r"Deliver by:\s*(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]{3})")
_DELIVERED_BADGE_RE = re.compile(r'<span class="badge (?P<classes>[^"]*)">Delivered</span>')
_MONTHS = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
_LONDON = ZoneInfo("Europe/London")
_CUTOFF_PREFIX = "fbm_carrier_cutoff:"


def _clean_fbm_journey_html(html: str) -> str:
    value = str(html or "")
    for old, new in _JOURNEY_LABEL_REPLACEMENTS:
        value = value.replace(old, new)
    return value


def _inject_once(html: str, marker: str, payload: str, closing: str) -> str:
    value = str(html or "")
    if marker in value:
        return value
    return value.replace(closing, payload + closing, 1) if closing in value else value + payload


def _align_fbm_tracking_link_html(html: str) -> str:
    return _inject_once(html, 'id="bt38FbmTrackingLinkAlignment"', _TRACKING_LINK_STYLE, '</head>')


def _align_fbm_marketplace_badge_html(html: str) -> str:
    return _inject_once(html, 'id="bt38FbmMarketplaceBadgeAlignment"', _MARKETPLACE_BADGE_STYLE, '</head>')


def _align_fbm_promise_journey_html(html: str) -> str:
    return _inject_once(html, 'id="bt38FbmPromiseJourneyAlignment"', _PROMISE_JOURNEY_SCRIPT, '</body>')


def _align_fbm_event_session_refresh_html(html: str) -> str:
    return _inject_once(html, 'id="bt38FbmEventSessionRefreshAlignment"', _EVENT_SESSION_REFRESH_SCRIPT, '</body>')


def _align_fbm_scroll_position_html(html: str) -> str:
    return _inject_once(html, 'id="bt38FbmScrollPositionAlignment"', _SCROLL_POSITION_SCRIPT, '</body>')


def _align_fbm_inline_shipping_script(html: str) -> str:
    return _inject_once(html, 'id="bt38FbmInlineShippingAlignment"', _INLINE_SHIPPING_SCRIPT, '</body>')


def _align_fbm_buyer_messages_card(html: str) -> str:
    value = str(html or "")
    pattern = re.compile(r'<div class="fbm-period-card(?P<class_suffix>[^"]*)" tabindex="0"><div class="fbm-period-label">Mapping review</div><div class="fbm-period-value">[^<]*</div><div class="fbm-period-tip" role="tooltip">.*?</div></div>', re.DOTALL)
    replacement = ('<div class="fbm-period-card\\g<class_suffix>" tabindex="0"><div class="fbm-period-label">Buyer messages</div><div class="fbm-period-value">0</div><div class="fbm-period-tip" role="tooltip"><div>No buyer messages are currently ingested into BT38.</div></div></div>')
    return pattern.sub(replacement, value, count=1)


def _cutoff_key(provider: str, carrier: str, service: str) -> str:
    norm = lambda v: " ".join(str(v or "").strip().casefold().split())
    return _CUTOFF_PREFIX + "|".join((norm(provider), norm(carrier), norm(service)))


def _saved_cutoffs() -> dict[str, str]:
    from models import SystemConfig
    rows = SystemConfig.query.filter(SystemConfig.key.like(f"{_CUTOFF_PREFIX}%")).all()
    result: dict[str, str] = {}
    for row in rows:
        try:
            payload = json.loads(row.value or "{}")
        except Exception:
            payload = {}
        value = str(payload.get("cutoff_time") or "").strip()
        if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            result[str(row.key)] = value
    return result


def _money(rate: dict[str, Any]) -> tuple[float | None, str]:
    price = rate.get("price")
    if isinstance(price, dict):
        raw = price.get("value") if price.get("value") is not None else price.get("total_price")
        currency = str(price.get("unit") or price.get("currency") or "GBP")
    else:
        raw, currency = price, "GBP"
    try:
        return float(raw), currency
    except (TypeError, ValueError):
        return None, currency


def _rate_identity(rate: dict[str, Any]) -> tuple[str, str, str]:
    carrier = str(rate.get("carrier_name") or rate.get("carrier") or "").strip()
    service = str(rate.get("service_name") or rate.get("service") or "").strip()
    rate_id = str(rate.get("rate_id") or rate.get("id") or rate.get("service_id") or "").strip()
    return carrier, service, rate_id


def _delivery_days(rate: dict[str, Any]) -> int | None:
    raw = rate.get("delivery")
    if isinstance(raw, (int, float)):
        return max(0, int(raw))
    if isinstance(raw, dict):
        for key in ("days", "transit_days", "max_days"):
            try:
                if raw.get(key) is not None:
                    return max(0, int(raw[key]))
            except (TypeError, ValueError):
                pass
    text = str(raw or "").strip().lower()
    match = re.search(r"(\d+)\s*(?:working\s*)?(?:day|days)", text)
    return int(match.group(1)) if match else None


def _cutoff_open(cutoff: str, *, now: datetime) -> bool:
    try:
        hour, minute = [int(part) for part in cutoff.split(":", 1)]
        return now.time().replace(tzinfo=None) <= now.replace(hour=hour, minute=minute, second=0, microsecond=0).time().replace(tzinfo=None)
    except Exception:
        return False


def _rate_can_meet_promise(rate: dict[str, Any], *, due: date | None, cutoff: str, now: datetime) -> bool:
    if due is None or not _cutoff_open(cutoff, now=now):
        return False
    days = _delivery_days(rate)
    if days is None:
        return False
    cursor = now.date()
    remaining = days
    while remaining > 0:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            remaining -= 1
    return cursor <= due


def _row_recommendation_evidence(row_ids: set[int]) -> dict[int, dict[str, Any]]:
    if not row_ids:
        return {}
    from extensions import db
    from fbm_models import FBMRateQuote
    from models import MarketplaceOrder
    from services.fbm_order_mapper import parcel_from_db

    rows = db.session.query(MarketplaceOrder).filter(MarketplaceOrder.id.in_(sorted(row_ids))).all()
    result: dict[int, dict[str, Any]] = {}
    now = datetime.utcnow()
    for row in rows:
        try:
            parcel = parcel_from_db(row).to_dict()
        except Exception:
            parcel = {}
        complete = all(float(parcel.get(name) or 0) > 0 for name in ("weight_kg", "length_cm", "width_cm", "height_cm"))
        quote = (
            FBMRateQuote.query
            .filter_by(store_id=row.store_id, marketplace_order_id=row.marketplace_order_id, provider="packlink")
            .filter((FBMRateQuote.expires_at.is_(None)) | (FBMRateQuote.expires_at > now))
            .order_by(FBMRateQuote.created_at.desc(), FBMRateQuote.id.desc())
            .first()
        )
        result[int(row.id)] = {"parcel": parcel, "parcel_complete": complete, "quote": quote}
    return result


def _align_fbm_recommended_shipping_html(html: str) -> str:
    """Resolve shipping inline from persisted evidence; never call or guess on page load."""
    value = str(html or "")
    row_ids = {int(match.group("row_id")) for match in _FBM_ROW_RE.finditer(value)}
    evidence = _row_recommendation_evidence(row_ids)
    cutoffs = _saved_cutoffs()
    now_local = datetime.now(_LONDON)

    def replace_row(match: re.Match[str]) -> str:
        row_id = int(match.group("row_id"))
        body = match.group("body")
        cell_match = _SHIPPING_CELL_RE.search(body)
        if cell_match is None:
            return match.group(0)
        old_cell = cell_match.group("body")
        promise_match = _MARKETPLACE_PROMISE_SERVICE_RE.search(old_cell)
        promise_html = ('<div class="small text-muted">Marketplace promise</div><strong>' + promise_match.group("service") + '</strong>') if promise_match else '<div class="small text-muted">Marketplace promise</div><strong class="text-muted">Pending</strong>'
        due = _promise_date_from_row(body, None)
        item = evidence.get(row_id) or {}
        parcel = item.get("parcel") or {}
        quote = item.get("quote")
        recommendation = ''

        if not item.get("parcel_complete"):
            recommendation = (f'<div class="bt38-inline-shipping mt-2"><div class="small text-muted">Recommended shipping</div><strong>Parcel details required</strong><div class="fbm-row-note text-muted">Add or change the real weight/dimensions before BT38 can select shipping.</div><button class="btn btn-sm btn-outline-primary fbm-shipping-options mt-1" type="button" data-order-id="{row_id}">Add / change parcel</button></div>')
        elif quote is None:
            recommendation = (f'<div class="bt38-inline-shipping mt-2"><div class="small text-muted">Recommended shipping</div><strong>Rates not saved</strong><div class="fbm-row-note text-muted">Get rates once. BT38 then reuses the saved quote until it expires; page loads never call Packlink.</div><button class="btn btn-sm btn-outline-primary bt38-get-saved-rates mt-1" type="button" data-order-id="{row_id}" data-parcel="{escape(json.dumps(parcel), quote=True)}">Get rates</button></div>')
        else:
            rates = [rate for rate in (quote.rates or []) if isinstance(rate, dict)]
            eligible: list[tuple[float, str, dict[str, Any], str]] = []
            missing_cutoff: list[dict[str, Any]] = []
            for rate in rates:
                carrier, service, rate_id = _rate_identity(rate)
                if not carrier or not service or not rate_id:
                    continue
                cutoff = cutoffs.get(_cutoff_key("packlink", carrier, service))
                if not cutoff:
                    missing_cutoff.append(rate)
                    continue
                amount, currency = _money(rate)
                if amount is not None and _rate_can_meet_promise(rate, due=due, cutoff=cutoff, now=now_local):
                    eligible.append((amount, currency, rate, cutoff))
            if eligible:
                amount, currency, chosen, cutoff = min(eligible, key=lambda item: item[0])
                carrier, service, rate_id = _rate_identity(chosen)
                recommendation = (f'<div class="bt38-inline-shipping mt-2"><div class="small text-muted">Recommended shipping</div><strong>{escape(carrier)} · {escape(service)}</strong><div class="small">{escape(currency)} {amount:.2f}</div><div class="fbm-row-note text-success">Meets delivery promise · confirmed cutoff {escape(cutoff)}</div><button class="btn btn-sm btn-success bt38-prepare-recommended-label mt-1" type="button" data-order-id="{row_id}" data-quote-id="{quote.id}" data-rate-id="{escape(rate_id, quote=True)}" data-carrier="{escape(carrier, quote=True)}">Prepare label</button><button class="btn btn-sm btn-link fbm-shipping-options mt-1" type="button" data-order-id="{row_id}">Change parcel</button></div>')
            elif missing_cutoff:
                options = ['<option value="">Choose carrier/service</option>']
                for rate in missing_cutoff:
                    carrier, service, _ = _rate_identity(rate)
                    payload = escape(json.dumps({"carrier": carrier, "service": service}), quote=True)
                    options.append(f'<option value="{payload}">{escape(carrier)} · {escape(service)}</option>')
                recommendation = (f'<div class="bt38-inline-shipping mt-2"><div class="small text-muted">Recommended shipping</div><strong>Cutoff required</strong><div class="fbm-row-note text-muted">Choose the service you actually use, then enter its real cutoff. For drop-off, confirm it with the shop; for collection, use your known collection time. BT38 never guesses.</div><select class="form-select form-select-sm bt38-cutoff-service mt-1">{"".join(options)}</select><input class="form-control form-control-sm bt38-cutoff-time mt-1" type="time" aria-label="Carrier cutoff"><button class="btn btn-sm btn-outline-primary bt38-save-cutoff mt-1" type="button">Save cutoff</button><button class="btn btn-sm btn-link fbm-shipping-options mt-1" type="button" data-order-id="{row_id}">Change parcel</button></div>')
            else:
                recommendation = (f'<div class="bt38-inline-shipping mt-2"><div class="small text-muted">Recommended shipping</div><strong>No proven eligible service</strong><div class="fbm-row-note text-muted">No saved rate can currently be proven to meet the promise using confirmed cutoff data.</div><button class="btn btn-sm btn-link fbm-shipping-options mt-1" type="button" data-order-id="{row_id}">Change parcel</button></div>')

        replacement = '<td class="fbm-route-cell">' + promise_html + recommendation + '</td>'
        body = body[:cell_match.start()] + replacement + body[cell_match.end():]
        return match.group(1) + body + match.group(4)

    return _FBM_ROW_RE.sub(replace_row, value)


def _delivery_evidence_by_order_row(order_row_ids: set[int]) -> dict[int, dict[str, Any]]:
    if not order_row_ids:
        return {}
    from extensions import db
    from fbm_models import FBMShipment
    from models import MarketplaceOrder
    displayed_rows = db.session.query(MarketplaceOrder.id, MarketplaceOrder.store_id, MarketplaceOrder.marketplace_order_id, MarketplaceOrder.created_at).filter(MarketplaceOrder.id.in_(sorted(order_row_ids))).all()
    identity_by_row_id = {int(row.id):(int(row.store_id),str(row.marketplace_order_id),row.created_at) for row in displayed_rows if row.id is not None and row.store_id is not None and row.marketplace_order_id}
    identities = sorted({(store_id, order_id) for store_id, order_id, _ in identity_by_row_id.values()})
    if not identities:
        return {}
    shipment_rows = db.session.query(FBMShipment.store_id, FBMShipment.marketplace_order_id, FBMShipment.delivered_at, FBMShipment.id).filter(tuple_(FBMShipment.store_id, FBMShipment.marketplace_order_id).in_(identities)).order_by(FBMShipment.id.desc()).all()
    latest_by_identity: dict[tuple[int,str],Any] = {}
    for row in shipment_rows:
        identity=(int(row.store_id),str(row.marketplace_order_id))
        if identity not in latest_by_identity:
            latest_by_identity[identity]=row.delivered_at
    return {row_id:{"created_at":created_at,"delivered_at":latest_by_identity.get((store_id,order_id))} for row_id,(store_id,order_id,created_at) in identity_by_row_id.items()}


def _promise_date_from_row(body: str, created_at: datetime | None) -> date | None:
    match = _DELIVER_BY_RE.search(body)
    if match is None:
        return None
    month = _MONTHS.get(match.group("month").lower())
    if month is None:
        return None
    try:
        day=int(match.group("day")); anchor=(created_at or datetime.utcnow()).date(); due=date(anchor.year,month,day)
        if due < anchor:
            due=date(anchor.year+1,month,day)
        return due
    except (TypeError,ValueError):
        return None


def _enrich_fbm_delivery_timing_html(html: str, *, today: date | None = None) -> str:
    value=str(html or ""); row_ids={int(match.group("row_id")) for match in _FBM_ROW_RE.finditer(value)}; evidence_by_row=_delivery_evidence_by_order_row(row_ids)
    if not evidence_by_row:
        return value
    today=today or datetime.utcnow().date()
    def replace_row(match: re.Match[str]) -> str:
        row_id=int(match.group("row_id")); body=match.group("body"); evidence=evidence_by_row.get(row_id) or {}; delivered_at=evidence.get("delivered_at"); due=_promise_date_from_row(body,evidence.get("created_at")); badge_match=_DELIVERED_BADGE_RE.search(body)
        if badge_match is None:
            return match.group(0)
        if delivered_at is not None and due is not None:
            delivered_date=delivered_at.date() if hasattr(delivered_at,"date") else None
            replacement='<span class="badge bg-danger">Delivered late</span>' if delivered_date is not None and delivered_date > due else '<span class="badge bg-success">Delivered</span><span class="badge bg-success bt38-on-time-badge">On time</span>'
            body=body[:badge_match.start()]+replacement+body[badge_match.end():]
        elif delivered_at is not None:
            body=body[:badge_match.start()]+'<span class="badge bg-primary">Delivered</span>'+body[badge_match.end():]
        elif due is not None and today > due:
            delayed='<span class="badge bg-danger bt38-delayed-badge">Delayed</span>'
            if delayed not in body:
                body=body[:badge_match.end()]+delayed+body[badge_match.end():]
        return match.group(1)+body+match.group(4)
    return _FBM_ROW_RE.sub(replace_row,value)


def _sale_identity(record: dict[str, Any]) -> tuple[int, str] | None:
    if str(record.get("log_type") or "") != "marketplace_sale":
        return None
    event_key=str(record.get("event_key") or ""); parts=event_key.split(":",3)
    if len(parts)<4 or parts[0]!="order":
        return None
    try:
        store_id=int(parts[1])
    except (TypeError,ValueError):
        return None
    order_id=str(parts[2] or "").strip()
    return (store_id,order_id) if order_id else None


def install_governed_order_clarity_alignment(app) -> None:
    if getattr(app,"_bt38_order_clarity_alignment_installed",False):
        return
    from services.governed_fbm_lifecycle_alignment import install_governed_fbm_lifecycle_alignment
    from services.governed_fbm_marketplace_dispatch_authority_alignment import install_governed_fbm_marketplace_dispatch_authority_alignment
    from services.governed_fbm_fulfillment_guard import install_governed_fbm_fulfillment_guard
    from services.fbm_db_delivery_promise_alignment import install_fbm_db_delivery_promise_alignment
    from services.governed_fbm_global_search_alignment import install_governed_fbm_global_search_alignment
    from services.governed_fbm_all_orders_health_alignment import install_governed_fbm_all_orders_health_alignment
    from services.governed_fbm_overdue_alert_alignment import install_governed_fbm_overdue_alert_alignment

    install_fbm_db_delivery_promise_alignment(app); install_governed_fbm_global_search_alignment(app); install_governed_fbm_all_orders_health_alignment(app); install_governed_fbm_overdue_alert_alignment(app); install_governed_fbm_lifecycle_alignment(app); install_governed_fbm_marketplace_dispatch_authority_alignment(); install_governed_fbm_fulfillment_guard(app)
    app._bt38_order_clarity_alignment_installed=True

    @app.post('/fbm/carrier-cutoff')
    @login_required
    def bt38_save_fbm_carrier_cutoff():
        from extensions import db
        from models import SystemConfig
        payload=request.get_json(silent=True) or {}
        provider=str(payload.get('provider') or '').strip(); carrier=str(payload.get('carrier') or '').strip(); service=str(payload.get('service') or '').strip(); cutoff=str(payload.get('cutoff_time') or '').strip()
        if not provider or not carrier or not service:
            return jsonify({'success':False,'message':'Provider, carrier and service are required.'}),400
        if re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',cutoff) is None:
            return jsonify({'success':False,'message':'Enter the actual cutoff as HH:MM.'}),400
        key=_cutoff_key(provider,carrier,service); value=json.dumps({'provider':provider,'carrier':carrier,'service':service,'cutoff_time':cutoff,'timezone':'Europe/London','source':'user_confirmed'})
        row=SystemConfig.query.filter_by(key=key).first()
        if row is None:
            row=SystemConfig(key=key,value=value); db.session.add(row)
        else:
            row.value=value
        db.session.commit()
        return jsonify({'success':True,'carrier':carrier,'service':service,'cutoff_time':cutoff,'timezone':'Europe/London','guessed':False})

    @app.after_request
    def bt38_order_clarity_response(response):
        path=request.path.rstrip('/') or '/'
        if path=='/fbm' and response.status_code==200 and response.content_type and 'text/html' in response.content_type:
            html=_clean_fbm_journey_html(response.get_data(as_text=True)); html=_align_fbm_recommended_shipping_html(html); html=_enrich_fbm_delivery_timing_html(html); html=_align_fbm_tracking_link_html(html); html=_align_fbm_marketplace_badge_html(html); html=_align_fbm_buyer_messages_card(html); html=_align_fbm_promise_journey_html(html); html=_align_fbm_event_session_refresh_html(html); html=_align_fbm_scroll_position_html(html); html=_align_fbm_inline_shipping_script(html); response.set_data(html)
        return response

    app.logger.info('BT38 order clarity alignment installed: persisted delivery promises + same-page DB-first shipping recommendation using saved rates and user-confirmed cutoffs + paid-label-only print boundary + persisted courier delivery timing + event-only refresh; no provider call on FBM page render')
