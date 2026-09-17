"""Final notification-bell authority: display the current FBM browser-session state only.

The bell owns no order lifecycle state and performs no database, marketplace or
carrier reads. The FBM page projects each rendered order's current journey into
the existing browser-session notification cache. The existing bell GET endpoint
returns an empty transport envelope; the installed browser cache merger supplies
the current FBM display records. There is no polling, timer, EventSource or
background fetch.
"""
from __future__ import annotations

from flask import jsonify
from flask_login import login_required


def _display_only_reader():
    return jsonify({
        "success": True,
        "records": [],
        "action_count": 0,
        "latest_event_at": None,
        "source": "fbm_browser_session_display_only",
        "bell_authority": False,
        "database_calls": False,
        "marketplace_calls": False,
        "polling": False,
    })


def _fbm_bell_session_script() -> str:
    return r'''<script id="bt38FbmBellDisplayOnlyAuthority">
(function(){
  var table=document.querySelector('.fbm-orders-table');
  if(!table)return;
  var cacheKey='bt38.notifications.exactEventRecords.v2';
  function text(node){return String(node&&node.textContent||'').trim();}
  function norm(value){return String(value||'').trim().toLowerCase().replace(/[- ]/g,'_');}
  function read(){try{var rows=JSON.parse(localStorage.getItem(cacheKey)||'[]');return Array.isArray(rows)?rows:[];}catch(_){return [];}}
  function label(row){
    var journey=text(row.querySelector('td:nth-child(9)'));
    if(journey.indexOf('Delivered')>=0)return 'Delivered';
    if(journey.indexOf('In transit')>=0)return 'In transit';
    if(journey.indexOf('Picked up')>=0)return 'Picked up';
    var shipment=text(row.querySelector('td:nth-child(8)'));
    if(shipment&&shipment.indexOf('Unshipped')<0)return 'Dispatched';
    return 'Ready to dispatch';
  }
  function project(row){
    var orderId=text(row.querySelector('td:nth-child(3) .fw-semibold');if(!orderId)return null;
    var marketCell=row.querySelector('td:nth-child(2)'),logo=marketCell&&marketCell.querySelector('.fbm-marketplace-logo');
    var platform=String(logo&&logo.getAttribute('alt')||text(marketCell&&marketCell.querySelector('strong'))||'Marketplace').trim();
    var product=text(row.querySelector('td:nth-child(4) strong')),qty=text(row.querySelector('td:nth-child(5)')),sku=text(row.querySelector('td:nth-child(4) code'));
    var carrier=text(row.querySelector('td:nth-child(8) strong')),tracking=text(row.querySelector('td:nth-child(8) code')),state=label(row);
    var parts=['Order '+orderId];if(qty)parts.push('Qty '+qty);if(carrier)parts.push('Carrier '+carrier);if(tracking)parts.push('Tracking '+tracking);
    return {event_key:'fbm-current:'+orderId,id:'fbm-current:'+orderId,log_type:state==='Ready to dispatch'?'marketplace_sale':'marketplace_lifecycle',platform:platform,title:state+' · '+platform+' · '+(product||orderId),message:parts.join(' · '),order_id:orderId,sku:sku,product_title:product,quantity:qty,carrier:carrier,tracking_number:tracking,status_label:state,requires_action:state==='Ready to dispatch',created_at:new Date().toISOString(),notification_source:'fbm_page'};
  }
  function sync(){
    var current={},projected=[];
    table.querySelectorAll('tbody tr.fbm-order-row').forEach(function(row){var record=project(row);if(record){current[record.order_id]=true;projected.push(record);}});
    // FBM current state replaces older lifecycle displays for the same order.
    var retained=read().filter(function(record){var orderId=String(record&&record.order_id||'').trim();return !orderId||!current[orderId];});
    try{localStorage.setItem(cacheKey,JSON.stringify(projected.concat(retained).slice(0,50)));}catch(_){}
  }
  sync();
  document.addEventListener('bt38:exact-record-event',function(){setTimeout(sync,0);});
})();
</script>'''


def install_governed_fbm_bell_display_only_alignment(app) -> None:
    if getattr(app, "_bt38_fbm_bell_display_only_alignment_installed", False):
        return
    endpoint = "governed.governed_ui_notifications"
    if endpoint not in app.view_functions:
        raise RuntimeError("governed notification endpoint is not registered")
    app.view_functions[endpoint] = login_required(_display_only_reader)

    @app.after_request
    def inject_fbm_bell_display_only(response):
        if response.status_code != 200 or not response.content_type or "text/html" not in response.content_type:
            return response
        try:
            from flask import request
            if request.path.rstrip("/") != "/fbm":
                return response
            html = response.get_data(as_text=True)
            if "bt38FbmBellDisplayOnlyAuthority" in html:
                return response
            script = _fbm_bell_session_script()
            html = html.replace("</body>", script + "</body>", 1) if "</body>" in html else html + script
            response.set_data(html)
            response.headers["Content-Length"] = str(len(response.get_data()))
        except Exception:
            app.logger.exception("FBM bell display-only injection failed")
        return response

    app._bt38_fbm_bell_display_only_alignment_installed = True
    app.logger.info("BT38 Bell final authority: FBM browser-session display only; zero DB/API reads; zero polling")
