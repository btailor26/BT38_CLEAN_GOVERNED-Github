"""Keep the notification bell on the existing FBM page/session event path.

The bell is presentation only. It never queries Neon, marketplace APIs or carrier
APIs. Generic committed order/shipment transport events are not user-facing
notifications. FBM notifications are projected from the already-rendered FBM
row so the bell and the small movement box mirror the same marketplace, Prime,
product, carrier/tracking and journey state already owned by FBM.
"""
from __future__ import annotations

from flask_login import login_required


_PRESENTATION_SCOPE_KEYS = (
    "platform", "marketplace_order_id", "status", "lifecycle_status", "quantity",
    "carrier", "tracking_number", "product_title", "fulfillment_type", "provider",
    "is_prime", "notification_label", "notification_source",
)


def _normalise(value) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _is_generic_transport_event(event: dict) -> bool:
    event_type = _normalise(event.get("event_type")); source = _normalise(event.get("source"))
    return event_type in {"order_committed", "shipment_committed"} and source in {"committed_marketplace_state", "server_commit", "browser_leader"}


def _label_for_event(event: dict) -> str | None:
    explicit = str(event.get("notification_label") or "").strip()
    if explicit: return explicit
    if _is_generic_transport_event(event): return None
    values = " ".join(_normalise(event.get(key)) for key in ("lifecycle_status", "status", "event_type", "source") if event.get(key) not in (None, ""))
    ordered = (
        (("return_fulfillment_completed", "return_closed", "returned"), "Returned"),
        (("return_requested", "return_fulfillment_initiated"), "Return requested"),
        (("refund_requested",), "Refund requested"), (("refunded", "refund_completed", "refund_issued"), "Refunded"),
        (("cancellation_requested", "cancel_requested"), "Cancellation requested"), (("cancelled", "canceled"), "Cancelled"),
        (("replacement_requested",), "Replacement requested"), (("replacement", "replaced"), "Replacement"),
        (("chargeback",), "Chargeback"), (("dispute",), "Dispute"), (("case_open", "case_opened"), "Issue / case"),
        (("late", "overdue", "ship_by_missed", "dispatch_deadline_missed"), "Late"), (("ship_by", "shipby", "dispatch_by", "dispatch_deadline"), "Ship by"),
        (("delivered",), "Delivered"), (("out_for_delivery",), "Out for delivery"), (("in_transit",), "In transit"),
        (("carrier_accepted", "picked_up", "collected", "accepted"), "Picked up"),
        (("marketplace_dispatch_confirmed", "label_assigned", "dispatched", "shipped", "partially_shipped"), "Shipped"),
        (("pending", "unshipped", "confirmed", "order_received", "new_order"), "Sale"),
    )
    for tokens, label in ordered:
        if any(token in values for token in tokens): return label
    source = _normalise(event.get("source")); order_id = str(event.get("order_id") or event.get("marketplace_order_id") or "").strip(); sku = str(event.get("seller_sku") or event.get("sku") or "").strip()
    if source in {"webhook_amazon", "webhook_ebay"} and order_id and sku: return "Sale"
    return None


def _platform_for_event(event: dict) -> str:
    explicit = str(event.get("platform") or "").strip()
    if explicit: return explicit
    source = _normalise(event.get("source"))
    if "amazon" in source: return "Amazon"
    if "ebay" in source: return "eBay"
    return "Marketplace"


def _event_to_bell_record(event: dict) -> dict | None:
    label = _label_for_event(event)
    if not label: return None
    revision = int(event.get("revision") or 0); order_id = str(event.get("order_id") or event.get("marketplace_order_id") or "").strip(); sku = str(event.get("seller_sku") or event.get("sku") or "").strip(); platform = _platform_for_event(event)
    product_title = str(event.get("product_title") or "").strip(); quantity = event.get("quantity"); carrier = str(event.get("carrier") or event.get("provider") or "").strip(); tracking = str(event.get("tracking_number") or "").strip(); is_prime = bool(event.get("is_prime"))
    subject = product_title or (f"Order {order_id}" if order_id else "Order"); title = f"{label} · {platform} · {subject}"
    if is_prime: title = f"{label} · {platform} Prime · {subject}"
    details = []
    if order_id: details.append(f"Order {order_id}")
    if quantity not in (None, ""): details.append(f"Qty {quantity}")
    if carrier: details.append(f"Carrier {carrier}")
    if tracking: details.append(f"Tracking {tracking}")
    message = " · ".join(details) if details else title
    return {"event_key": f"runtime:{revision}:{_normalise(label)}:{order_id}:{sku}", "id": f"runtime:{revision}", "log_type": "marketplace_sale" if label in {"Sale", "Get ready to dispatch"} else "marketplace_lifecycle", "platform": platform, "title": title, "message": message, "order_id": order_id, "sku": sku, "product_title": product_title, "quantity": quantity, "carrier": carrier, "tracking_number": tracking, "is_prime": is_prime, "lifecycle_status": _normalise(event.get("lifecycle_status") or event.get("status")), "status_label": label, "created_at": event.get("published_at")}


def _patch_exact_scope() -> None:
    from fbm_models import FBMShipment
    from models import MarketplaceOrder
    from services import governed_exact_record_event_alignment as exact
    from services import governed_ui_event_signal as ui
    ui._SINGULAR_SCOPE_KEYS = tuple(dict.fromkeys(tuple(ui._SINGULAR_SCOPE_KEYS) + _PRESENTATION_SCOPE_KEYS))
    if getattr(exact, "_bt38_bell_projection_scope_patched", False): return
    original = exact._row_scope
    def projected_scope(row):
        scope = dict(original(row) or {})
        if isinstance(row, MarketplaceOrder):
            scalar = {"marketplace_order_id": getattr(row, "marketplace_order_id", None), "status": getattr(row, "status", None), "lifecycle_status": getattr(row, "status", None), "quantity": getattr(row, "quantity", None), "carrier": getattr(row, "carrier", None), "tracking_number": getattr(row, "tracking_number", None), "product_title": getattr(row, "product_title", None), "fulfillment_type": getattr(row, "fulfillment_type", None), "platform": getattr(row, "platform", None) or getattr(row, "marketplace", None)}
            scope.update({key: value for key, value in scalar.items() if value not in (None, "")})
        elif isinstance(row, FBMShipment):
            scalar = {"status": getattr(row, "status", None), "lifecycle_status": getattr(row, "status", None), "carrier": getattr(row, "carrier", None), "tracking_number": getattr(row, "tracking_number", None), "provider": getattr(row, "provider", None)}
            scope.update({key: value for key, value in scalar.items() if value not in (None, "")})
        return scope
    exact._row_scope = projected_scope; exact._bt38_bell_projection_scope_patched = True


def _browser_event_cache_script() -> str:
    return r'''
<script id="bt38ExactBellBrowserCache">
(function(){
  if(window.bt38ExactBellBrowserCacheInstalled)return;window.bt38ExactBellBrowserCacheInstalled=true;
  var legacyKeys=['bt38.notifications.exactEventRecords.v1','bt38.notifications.fbmMovementState.v1'];legacyKeys.forEach(function(key){try{localStorage.removeItem(key);}catch(_){}});
  var cacheKey='bt38.notifications.exactEventRecords.v2',movementKey='bt38.notifications.fbmMovementState.v2';
  function norm(value){return String(value||'').trim().toLowerCase().replace(/[- ]/g,'_');}
  function isGenericTransport(detail){var type=norm(detail&&detail.event_type),source=norm(detail&&detail.source);return (type==='order_committed'||type==='shipment_committed')&&(source==='committed_marketplace_state'||source==='server_commit'||source==='browser_leader');}
  function labelFor(detail){
    var explicit=String(detail.notification_label||'').trim();if(explicit)return explicit;if(isGenericTransport(detail))return '';
    var value=[detail.lifecycle_status,detail.status,detail.event_type,detail.source].map(norm).join(' '),rules=[
      [['return_fulfillment_completed','return_closed','returned'],'Returned'],[['return_requested','return_fulfillment_initiated'],'Return requested'],[['refund_requested'],'Refund requested'],[['refunded','refund_completed','refund_issued'],'Refunded'],[['cancellation_requested','cancel_requested'],'Cancellation requested'],[['cancelled','canceled'],'Cancelled'],[['replacement_requested'],'Replacement requested'],[['replacement','replaced'],'Replacement'],[['chargeback'],'Chargeback'],[['dispute'],'Dispute'],[['case_open','case_opened'],'Issue / case'],[['late','overdue','ship_by_missed','dispatch_deadline_missed'],'Late'],[['ship_by','shipby','dispatch_by','dispatch_deadline'],'Ship by'],[['delivered'],'Delivered'],[['out_for_delivery'],'Out for delivery'],[['in_transit'],'In transit'],[['carrier_accepted','picked_up','collected','accepted'],'Picked up'],[['marketplace_dispatch_confirmed','label_assigned','dispatched','shipped','partially_shipped'],'Shipped'],[['pending','unshipped','confirmed','order_received','new_order'],'Sale']];
    for(var i=0;i<rules.length;i++)if(rules[i][0].some(function(token){return value.indexOf(token)>=0;}))return rules[i][1];
    var source=norm(detail.source),orderId=String(detail.order_id||detail.marketplace_order_id||'').trim(),sku=String(detail.seller_sku||detail.sku||'').trim();if((source==='webhook_amazon'||source==='webhook_ebay')&&orderId&&sku)return 'Sale';return '';
  }
  function platformFor(detail){var explicit=String(detail.platform||'').trim();if(explicit)return explicit;var source=norm(detail.source);if(source.indexOf('amazon')>=0)return 'Amazon';if(source.indexOf('ebay')>=0)return 'eBay';return 'Marketplace';}
  function rank(label){var value=norm(label),ranks={ready_to_dispatch:1,get_ready_to_dispatch:1,sale:1,shipped:2,dispatched:2,picked_up:3,in_transit:4,out_for_delivery:5,delivered:6};return Number(ranks[value]||0);}
  function collapseCurrent(rows){var best={},other=[];(Array.isArray(rows)?rows:[]).forEach(function(row){if(!row)return;var orderId=String(row.order_id||'').trim();if(!orderId){other.push(row);return;}var current=best[orderId];if(!current||rank(row.status_label)>rank(current.status_label)||(rank(row.status_label)===rank(current.status_label)&&Date.parse(row.created_at||'')>Date.parse(current.created_at||'')))best[orderId]=row;});return Object.keys(best).map(function(key){return best[key];}).concat(other).sort(function(a,b){return Date.parse(b&&b.created_at||'')-Date.parse(a&&a.created_at||'');});}
  function read(){try{var value=JSON.parse(localStorage.getItem(cacheKey)||'[]');return collapseCurrent(Array.isArray(value)?value:[]);}catch(_){return [];}}
  window.BT38BellCurrentRecords=function(){return read().slice(0,50);};
  function write(rows){try{localStorage.setItem(cacheKey,JSON.stringify(collapseCurrent(rows).slice(0,50)));}catch(_){}}
  function readMovement(){try{var value=JSON.parse(localStorage.getItem(movementKey)||'{}');return value&&typeof value==='object'?value:{};}catch(_){return {};}}
  function writeMovement(value){try{localStorage.setItem(movementKey,JSON.stringify(value));}catch(_){}}
  function recordFor(detail){
    if(!detail||typeof detail!=='object')return null;var label=labelFor(detail);if(!label)return null;
    var revision=Number(detail.revision||0),orderId=String(detail.order_id||detail.marketplace_order_id||'').trim(),sku=String(detail.seller_sku||detail.sku||'').trim(),platform=platformFor(detail);
    var productTitle=String(detail.product_title||'').trim(),subject=productTitle||(orderId?'Order '+orderId:'Order'),carrier=String(detail.carrier||detail.provider||'').trim(),tracking=String(detail.tracking_number||'').trim();
    var quantity=detail.quantity,isPrime=detail.is_prime===true||String(detail.is_prime||'').toLowerCase()==='true',shipBy=String(detail.ship_by_at||detail.ship_by||'').trim(),parts=[];
    if(orderId)parts.push('Order '+orderId);if(quantity!==undefined&&quantity!==null&&quantity!=='')parts.push('Qty '+quantity);if((label==='Get ready to dispatch'||label==='Ship by'||label==='Late')&&shipBy&&norm(shipBy)!=='pending')parts.push('Ship by '+shipBy);if(carrier)parts.push('Carrier '+carrier);if(tracking)parts.push('Tracking '+tracking);
    var marketTitle=isPrime?platform+' Prime':platform,title=label+' · '+marketTitle+' · '+subject,message=parts.length?parts.join(' · '):title;
    return {event_key:'runtime:'+revision+':'+norm(label)+':'+orderId+':'+sku,id:'runtime:'+revision,log_type:(label==='Sale'||label==='Get ready to dispatch')?'marketplace_sale':'marketplace_lifecycle',platform:platform,title:title,message:message,order_id:orderId,sku:sku,product_title:productTitle,quantity:quantity,carrier:carrier,tracking_number:tracking,is_prime:isPrime,ship_by_at:shipBy,lifecycle_status:norm(detail.lifecycle_status||detail.status),status_label:label,requires_action:(label==='Sale'||label==='Get ready to dispatch'||label==='Late'||label==='Return requested'||label==='Refund requested'||label==='Cancellation requested'||label==='Replacement requested'||label==='Chargeback'||label==='Dispute'||label==='Issue / case'),created_at:detail.published_at||new Date().toISOString()};
  }
  function store(detail){var record=recordFor(detail);if(!record)return null;var rows=read(),exists=rows.some(function(row){return row&&row.event_key===record.event_key;});rows=rows.filter(function(row){return row&&row.event_key!==record.event_key;});rows.unshift(record);write(rows);return {record:record,isNew:!exists};}
  function fbmRowFor(orderId){var rows=document.querySelectorAll('.fbm-orders-table tbody .fbm-order-row');for(var i=0;i<rows.length;i++){var shown=rows[i].querySelector('td:nth-child(3) .fw-semibold');if(shown&&String(shown.textContent||'').trim()===orderId)return rows[i];}return null;}
  function text(node){return String(node&&node.textContent||'').trim();}
  function fbmLabel(row){var note=text(row.querySelector('td:nth-child(9) .text-danger'));if(note.indexOf('Carrier pickup overdue')>=0)return 'Late';var badges=row.querySelectorAll('td:nth-child(9) .badge.bg-success'),reached=[];for(var i=0;i<badges.length;i++)reached.push(text(badges[i]));if(reached.indexOf('Delivered')>=0)return 'Delivered';if(reached.indexOf('In transit')>=0)return 'In transit';if(reached.indexOf('Picked up')>=0)return 'Picked up';var shipment=text(row.querySelector('td:nth-child(8)'));if(shipment&&shipment.indexOf('Unshipped')<0)return 'Shipped';if(shipment.indexOf('Unshipped')>=0)return 'Get ready to dispatch';return '';}
  function fbmProjection(detail){
    var orderId=String(detail.order_id||detail.marketplace_order_id||'').trim();if(!orderId)return null;var row=fbmRowFor(orderId);if(!row)return null;var label=fbmLabel(row);if(!label)return null;
    var marketCell=row.querySelector('td:nth-child(2)'),logo=marketCell&&marketCell.querySelector('.fbm-marketplace-logo'),platform=String(logo&&logo.getAttribute('alt')||text(marketCell&&marketCell.querySelector('strong'))||'').trim(),prime=!!(marketCell&&marketCell.querySelector('img[alt="Prime"]'));
    var productTitle=text(row.querySelector('td:nth-child(4) strong')),quantity=text(row.querySelector('td:nth-child(5)')),shipBy=text(row.querySelector('td:nth-child(7) .fbm-promise-line span')),carrier=text(row.querySelector('td:nth-child(8) strong')),tracking=text(row.querySelector('td:nth-child(8) code'));
    return Object.assign({},detail,{notification_label:label,notification_source:'fbm_page',platform:platform,product_title:productTitle,quantity:quantity,ship_by_at:shipBy,carrier:carrier,tracking_number:tracking,is_prime:prime,source:'fbm_page'});
  }
  function showFbmToast(record){if(!record)return;var movement=readMovement(),key=String(record.order_id||record.event_key||'').trim();if(key&&movement[key]===record.status_label)return;if(key){movement[key]=record.status_label;writeMovement(movement);}var host=document.getElementById('bt38FbmMovementToasts');if(!host){host=document.createElement('div');host.id='bt38FbmMovementToasts';host.setAttribute('aria-live','polite');host.style.cssText='position:fixed;right:18px;top:78px;z-index:1085;width:min(360px,calc(100vw - 36px));display:flex;flex-direction:column;gap:8px;';document.body.appendChild(host);}var box=document.createElement('div');box.className='card shadow-sm border';box.style.cssText='padding:10px 12px;background:var(--bs-body-bg,#fff);';var heading=document.createElement('div');heading.className='fw-semibold small';heading.textContent=record.title;var meta=document.createElement('div');meta.className='small text-muted mt-1';meta.textContent=record.message||'';box.appendChild(heading);if(meta.textContent)box.appendChild(meta);host.appendChild(box);window.setTimeout(function(){if(box&&box.parentNode)box.parentNode.removeChild(box);},5000);}
  function seedFromRenderedFbm(){
    var rows=document.querySelectorAll('.fbm-orders-table tbody .fbm-order-row'),seeded=[];
    for(var i=0;i<rows.length;i++){
      var row=rows[i],shown=row.querySelector('td:nth-child(3) .fw-semibold'),orderId=text(shown);
      if(!orderId)continue;
      var label=fbmLabel(row);if(!label)continue;
      var marketCell=row.querySelector('td:nth-child(2)'),logo=marketCell&&marketCell.querySelector('.fbm-marketplace-logo'),platform=String(logo&&logo.getAttribute('alt')||text(marketCell&&marketCell.querySelector('strong'))||'').trim(),prime=!!(marketCell&&marketCell.querySelector('img[alt="Prime"]'));
      var productTitle=text(row.querySelector('td:nth-child(4) strong')),quantity=text(row.querySelector('td:nth-child(5)')),shipBy=text(row.querySelector('td:nth-child(7) .fbm-promise-line span')),carrier=text(row.querySelector('td:nth-child(8) strong')),tracking=text(row.querySelector('td:nth-child(8) code'));
      var detail={revision:0,order_id:orderId,marketplace_order_id:orderId,notification_label:label,notification_source:'fbm_page',platform:platform,product_title:productTitle,quantity:quantity,ship_by_at:shipBy,carrier:carrier,tracking_number:tracking,is_prime:prime,source:'fbm_page'};
      var record=recordFor(detail);if(record)seeded.push(record);
    }
    if(seeded.length)write(seeded.concat(read()));
  }
  window.BT38BellSeedFromRenderedFbm=seedFromRenderedFbm;
  window.addEventListener('bt38-marketplace-event',function(event){
    var detail=event&&event.detail||{},projected=fbmProjection(detail);
    if(projected){var saved=store(projected);if(saved&&saved.isNew)showFbmToast(saved.record);return;}
    if(isGenericTransport(detail))return;
    var saved=store(detail),owned=norm(detail.notification_source||detail.source);if(saved&&saved.isNew&&owned==='fbm_page')showFbmToast(saved.record);
  });
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',seedFromRenderedFbm,{once:true});else seedFromRenderedFbm();
  window.addEventListener('load',seedFromRenderedFbm,{once:true});
})();
</script>
'''


def _inject_browser_cache(response):
    if response.status_code != 200 or "text/html" not in str(response.content_type or "").lower(): return response
    html = response.get_data(as_text=True)
    if 'id="bt38NotificationBell"' not in html or 'id="bt38ExactBellBrowserCache"' in html: return response
    script = _browser_event_cache_script(); marker = "</body>"; response.set_data(html.replace(marker, script + marker, 1) if marker in html else html + script); return response


def install_governed_bell_event_projection_alignment(app) -> None:
    """Retired: the Bell has one display-only FBM projection owner."""
    app.logger.info("BT38 retired legacy exact-event Bell projection alignment")
