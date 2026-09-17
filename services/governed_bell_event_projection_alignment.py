"""Bell display alignment: mirror the current rendered FBM page only.

The bell owns no order/shipment state. The FBM page projects each rendered row's
current lifecycle into browser session storage. Opening the bell only reads that
browser projection through the existing notification GET response. No Bell DB
query, marketplace/carrier call, timer, interval, EventSource or polling path is
introduced here.
"""
from __future__ import annotations

from flask import jsonify
from flask_login import login_required


def _empty_display_reader():
    """Transport shell only; browser FBM projection supplies the records."""
    return jsonify({
        "success": True,
        "records": [],
        "action_count": 0,
        "latest_event_at": None,
        "source": "fbm_browser_session",
        "bell_authority": False,
        "database_calls": False,
        "marketplace_calls": False,
        "polling": False,
    })


def _browser_projection_script() -> str:
    return r'''
<script id="bt38FbmBellDisplayOnlyAlignment">
(function(){
  if(window.bt38FbmBellDisplayOnlyAlignmentInstalled)return;
  window.bt38FbmBellDisplayOnlyAlignmentInstalled=true;

  var cacheKey='bt38.notifications.fbmCurrentState.v1';
  function text(node){return String(node&&node.textContent||'').trim();}
  function read(){try{var value=JSON.parse(sessionStorage.getItem(cacheKey)||'[]');return Array.isArray(value)?value:[];}catch(_){return [];}}
  function write(rows){try{sessionStorage.setItem(cacheKey,JSON.stringify(rows.slice(0,50)));}catch(_){}}
  function label(row,info){
    var note=text(row.querySelector('td:nth-child(9) .text-danger'));
    if(note.indexOf('Carrier pickup overdue')>=0)return 'Late';
    var badges=row.querySelectorAll('td:nth-child(9) .badge.bg-success'),reached=[];
    for(var i=0;i<badges.length;i++)reached.push(text(badges[i]));
    if(reached.indexOf('Delivered')>=0)return 'Delivered';
    if(reached.indexOf('In transit')>=0)return 'In transit';
    if(reached.indexOf('Picked up')>=0)return 'Picked up';
    var queue=String(info&&info.queue||row.dataset.fbmQueue||'');
    if(queue==='ready_dispatch')return 'Ready to dispatch';
    if(queue==='dispatched')return 'Dispatched';
    if(queue==='cancelled')return 'Cancelled';
    if(queue==='replacements')return 'Replacement';
    if(queue==='refunds')return 'Refund / issue';
    return '';
  }
  function project(){
    var table=document.querySelector('.fbm-orders-table'),dataNode=document.getElementById('bt38FbmLifecycleTabsData');
    if(!table||!dataNode)return;
    var data={};try{data=JSON.parse(dataNode.textContent||'{}')}catch(_){return;}
    var projected=[];
    table.querySelectorAll('tbody tr.fbm-order-row').forEach(function(row){
      var info=data[row.dataset.orderId]||{},state=label(row,info);if(!state)return;
      var orderId=text(row.querySelector('td:nth-child(3) .fw-semibold');if(!orderId)return;
      var marketCell=row.querySelector('td:nth-child(2)'),logo=marketCell&&marketCell.querySelector('.fbm-marketplace-logo');
      var platform=String(logo&&logo.getAttribute('alt')||text(marketCell&&marketCell.querySelector('strong'))||'Marketplace').trim();
      var prime=!!(marketCell&&marketCell.querySelector('img[alt="Prime"]'));
      var product=text(row.querySelector('td:nth-child(4) strong')),qty=text(row.querySelector('td:nth-child(5)'));
      var carrier=text(row.querySelector('td:nth-child(8) strong')),tracking=text(row.querySelector('td:nth-child(8) code'));
      var created=String(info.created_at||row.dataset.fbmCreatedAt||new Date().toISOString());
      var subject=product||('Order '+orderId),marketTitle=prime?platform+' Prime':platform;
      var parts=['Order '+orderId];if(qty)parts.push('Qty '+qty);if(carrier)parts.push('Carrier '+carrier);if(tracking)parts.push('Tracking '+tracking);
      projected.push({event_key:'fbm-current:'+orderId,id:'fbm-current:'+orderId,log_type:state==='Ready to dispatch'?'marketplace_sale':'marketplace_lifecycle',platform:platform,title:state+' · '+marketTitle+' · '+subject,message:parts.join(' · '),order_id:orderId,product_title:product,quantity:qty,carrier:carrier,tracking_number:tracking,is_prime:prime,status_label:state,requires_action:state==='Ready to dispatch'||state==='Late',created_at:created});
    });
    projected.sort(function(a,b){return Date.parse(b.created_at||'')-Date.parse(a.created_at||'');});
    write(projected);
  }

  // Project once from the already-rendered FBM page. No timer/polling.
  project();
  window.addEventListener('bt38-fbm-committed-snapshot-applied',project);

  var previousFetch=window.fetch.bind(window);
  window.fetch=async function(input,init){
    var response=await previousFetch(input,init),url=typeof input==='string'?input:(input&&input.url)||'',method=String(init&&init.method||'GET').toUpperCase();
    if(method!=='GET'||url.indexOf('/governed/ui/notifications')!==0||!response.ok)return response;
    try{
      var payload=await response.clone().json();if(!payload||payload.success!==true)return response;
      var rows=read();payload.records=rows;payload.action_count=rows.filter(function(row){return row.requires_action===true;}).length;payload.latest_event_at=rows.length?rows[0].created_at:null;payload.source='fbm_browser_session';payload.bell_authority=false;payload.database_calls=false;payload.marketplace_calls=false;payload.polling=false;
      var headers=new Headers(response.headers);headers.set('Content-Type','application/json');return new Response(JSON.stringify(payload),{status:response.status,statusText:response.statusText,headers:headers});
    }catch(_){return response;}
  };
})();
</script>
'''


def _inject_projection(response):
    if response.status_code != 200 or "text/html" not in str(response.content_type or "").lower():
        return response
    html=response.get_data(as_text=True)
    if 'id="bt38NotificationBell"' not in html or 'id="bt38FbmBellDisplayOnlyAlignment"' in html:
        return response
    script=_browser_projection_script()
    response.set_data(html.replace("</body>",script+"</body>",1) if "</body>" in html else html+script)
    return response


def install_governed_bell_event_projection_alignment(app) -> None:
    endpoint="governed.governed_ui_notifications"
    if endpoint in app.view_functions:
        app.view_functions[endpoint]=login_required(_empty_display_reader)
    if not getattr(app,"_bt38_fbm_bell_display_only_installed",False):
        app.after_request(_inject_projection)
        app._bt38_fbm_bell_display_only_installed=True
    app.logger.info("BT38 bell display-only aligned: current rendered FBM state; zero DB/API reads; zero polling")
