"""Keep FBM committed-event refresh on the exact browser-session record.

The shared governed event already identifies the affected order. FBM must not GET
/fbm, rebuild the working set, query a marketplace/provider, poll or start a
second event stream when that event arrives. This late browser alignment captures
the existing event before the legacy full-page refresh listener and mutates only
the matching rendered record from facts carried by the committed event.
"""
from __future__ import annotations

from flask import request


def _script() -> str:
    return r'''<script id="bt38FbmExactRecordSessionAlignment">
(function(){
  if(window.bt38FbmExactRecordSessionAlignmentInstalled)return;
  window.bt38FbmExactRecordSessionAlignmentInstalled=true;
  function norm(v){return String(v||'').trim().toLowerCase().replace(/[- ]/g,'_');}
  function text(node,value){if(node&&value!==undefined&&value!==null&&String(value).trim()!=='')node.textContent=String(value);}
  function findRow(orderId){
    var rows=document.querySelectorAll('.fbm-orders-table tbody tr.fbm-order-row');
    for(var i=0;i<rows.length;i++){
      var shown=rows[i].querySelector('td:nth-child(3) .fw-semibold');
      if(shown&&String(shown.textContent||'').trim()===orderId)return rows[i];
    }
    return null;
  }
  function queue(status){
    status=norm(status);
    if(status==='pending')return 'pending';
    if(['shipped','dispatched','partially_shipped','fulfilled','completed','accepted','carrier_accepted','collected','picked_up','in_transit','out_for_delivery','delivered'].indexOf(status)>=0)return 'dispatched';
    if(status.indexOf('cancel')>=0)return 'cancelled';
    if(status.indexOf('replacement')>=0)return 'replacements';
    if(status.indexOf('return')>=0)return 'returns';
    if(status.indexOf('refund')>=0||status.indexOf('case')>=0||status.indexOf('dispute')>=0||status.indexOf('chargeback')>=0)return 'refunds';
    return 'ready_dispatch';
  }
  function localDay(value){if(!value)return null;var d=new Date(value);return isNaN(d.getTime())?null:new Date(d.getFullYear(),d.getMonth(),d.getDate());}
  function session(){
    var fallback={tab:'pending',search:'',range:'3d',from:'',to:''};
    return (window.BT38&&typeof window.BT38.getPageSession==='function')?window.BT38.getPageSession('fbm',fallback):fallback;
  }
  function inHistory(row,s){
    var d=localDay(row.dataset.fbmCreatedAt);if(!d)return false;
    var today=new Date();today=new Date(today.getFullYear(),today.getMonth(),today.getDate());
    var range=String(s.range||'3d').toLowerCase(),start=null,end=null;
    if(range==='custom'){
      start=s.from?new Date(String(s.from)+'T00:00:00'):null;
      end=s.to?new Date(String(s.to)+'T23:59:59'):null;
    }else{
      var days={'3d':3,'7d':7,'30d':30,'90d':90,'1y':365}[range]||3;
      start=new Date(today);start.setDate(start.getDate()-(days-1));
      end=new Date(today);end.setHours(23,59,59,999);
    }
    return !(start&&d<start)&&!(end&&d>end);
  }
  function applyActiveFiltersToExactRow(row){
    var s=session()||{},active=String(s.tab||'pending'),search=String(s.search||'').trim().toLowerCase();
    row.dataset.fbmSearch=(row.textContent||'').toLowerCase();
    var historyMatch=inHistory(row,s);
    row.dataset.fbmHistoryMatch=historyMatch?'1':'0';
    var matches=historyMatch&&String(row.dataset.fbmQueue||'')===active&&(!search||String(row.dataset.fbmSearch||'').indexOf(search)>=0);
    row.hidden=!matches;
  }
  function apply(detail){
    detail=detail&&typeof detail==='object'?detail:{};
    var orderId=String(detail.order_id||detail.marketplace_order_id||'').trim();
    if(!orderId)return false;
    var row=findRow(orderId);
    // A brand-new order is inserted by the governed snapshot owner; never rebuild
    // the entire FBM page here just because this browser has not rendered it yet.
    if(!row){
      window.dispatchEvent(new CustomEvent('bt38-fbm-exact-record-missing',{detail:detail}));
      return true;
    }
    var status=norm(detail.lifecycle_status||detail.status);
    if(status){row.dataset.lifecycleStatus=status;row.dataset.fbmQueue=queue(status);}
    if(detail.created_at)row.dataset.fbmCreatedAt=String(detail.created_at);
    var shipment=row.querySelector('td:nth-child(8)');
    if(shipment){
      text(shipment.querySelector('strong'),detail.carrier||detail.provider);
      text(shipment.querySelector('code'),detail.tracking_number);
    }
    var projected=null;
    var dataNode=document.getElementById('bt38FbmLifecycleTabsData');
    if(dataNode){
      try{
        var data=JSON.parse(dataNode.textContent||'{}'),key=String(row.dataset.orderId||'');
        if(key&&data[key]){
          if(status){data[key].status=status;data[key].queue=queue(status);}
          if(detail.created_at)data[key].created_at=detail.created_at;
          projected=data[key];
          dataNode.textContent=JSON.stringify(data);
        }
      }catch(_){}
    }
    // Active History/tab/search filters remain presentation-only. Re-evaluate only
    // this changed row; never call the legacy whole-snapshot render path.
    applyActiveFiltersToExactRow(row);
    window.dispatchEvent(new CustomEvent('bt38-fbm-committed-snapshot-applied',{detail:{order_id:orderId,row:row,committed:detail,projection:projected}}));
    return true;
  }
  window.addEventListener('bt38-marketplace-event',function(event){
    var detail=event&&event.detail||{};
    if(!String(detail.order_id||detail.marketplace_order_id||'').trim())return;
    // FBM owns this exact order handoff. Stop the older listener that GETs the
    // whole /fbm document and rebuilds every record.
    event.stopImmediatePropagation();
    apply(detail);
  },true);
})();
</script>'''


def install_governed_fbm_exact_record_session_alignment(app) -> None:
    if getattr(app, "_bt38_fbm_exact_record_session_alignment_installed", False):
        return

    @app.after_request
    def inject_exact_record_session_alignment(response):
        if request.path.rstrip("/") != "/fbm":
            return response
        if response.status_code != 200 or "text/html" not in str(response.content_type or "").lower():
            return response
        html=response.get_data(as_text=True)
        if "bt38FbmExactRecordSessionAlignment" in html:
            return response
        script=_script()
        response.set_data(html.replace("</body>",script+"</body>",1) if "</body>" in html else html+script)
        return response

    app._bt38_fbm_exact_record_session_alignment_installed=True
    app.logger.info("BT38 FBM exact-record session alignment: committed event updates one rendered record under active History/tab/search filters; no /fbm rebuild, provider read or polling")
