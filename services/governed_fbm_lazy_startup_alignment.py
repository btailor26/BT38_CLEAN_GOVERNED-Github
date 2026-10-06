"""Final FBM browser startup boundary.

The initial /fbm document is a DB-backed workspace shell. Feature assets must not
start merely because the page rendered. Existing feature implementations remain
unchanged and are loaded only by the user action or committed event that owns them.
No polling, provider reads, timers, or alternate authorities are introduced here.
"""
from __future__ import annotations

import re
from flask import request

_FEATURE_ASSETS = (
    "royal_mail_click_drop_connection.js",
    "fbm_qz_print.js",
    "fbm_tracking_journey.js",
    "fbm_replacement_label_alignment.js",
    "fbm_ebay_shipping_alignment.js",
    "fbm_event_session_refresh_alignment.js",
    "fbm_delivery_promise_journey_alignment.js",
    "fbm_scroll_position_alignment.js",
    "fbm_row_truth_alignment.js",
)

_BOOTSTRAP = r'''<script id="bt38FbmLazyFeatureBoundary">
(function(){
  const loaded = new Map();
  function load(name){
    if (loaded.has(name)) return loaded.get(name);
    const promise = new Promise((resolve,reject)=>{
      const script=document.createElement('script');
      script.src='/static/js/'+name;
      script.async=true;
      script.dataset.bt38LazyFeature=name;
      script.onload=()=>resolve(script);
      script.onerror=()=>{loaded.delete(name);reject(new Error('Unable to load '+name));};
      document.head.appendChild(script);
    });
    loaded.set(name,promise);
    return promise;
  }
  function replayAfter(name,event){
    event.preventDefault();
    event.stopImmediatePropagation();
    const target=event.target;
    void load(name).then(()=>{
      target.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window}));
    }).catch(error=>console.warn('[BT38 FBM] lazy feature unavailable',error));
  }
  document.addEventListener('click',event=>{
    const target=event.target && event.target.closest ? event.target.closest('*') : null;
    if(!target) return;
    if(target.closest('#royalMailConnectionCard,[data-bt38-royal-mail-legacy="1"],#royalMailApprovalModal')){
      if(!loaded.has('royal_mail_click_drop_connection.js')) return replayAfter('royal_mail_click_drop_connection.js',event);
    }
    if(target.closest('#qzConnect,#qzSavePrinter,.packlink-existing-status,#dispatchedPacklinkLabelAction')){
      if(!loaded.has('fbm_qz_print.js')) return replayAfter('fbm_qz_print.js',event);
    }
    if(target.closest('.provider-action[data-provider="ebay_shipping"],.ebay-native-buy')){
      if(!loaded.has('fbm_ebay_shipping_alignment.js')) return replayAfter('fbm_ebay_shipping_alignment.js',event);
    }
    if(target.closest('#readyToShipSelected,.fbm-shipping-options,.bt38-replacement-start,.bt38-replacement-label')){
      if(!loaded.has('fbm_replacement_label_alignment.js')) return replayAfter('fbm_replacement_label_alignment.js',event);
    }
  },true);

})();
</script>'''


def _strip_feature_assets(html: str) -> str:
    for asset in _FEATURE_ASSETS:
        pattern = re.compile(
            rf"""<script[^>]+src=["'][^"']*{re.escape(asset)}[^"']*["'][^>]*>\s*</script>""",
            re.IGNORECASE,
        )
        html = pattern.sub("", html)
    return html

def install_governed_fbm_lazy_startup_alignment(app) -> None:
    if getattr(app, "_bt38_fbm_lazy_startup_alignment_installed", False):
        return

    @app.after_request
    def _final_fbm_startup_boundary(response):
        if request.method != "GET" or request.path.rstrip("/") != "/fbm":
            return response
        if response.status_code != 200 or not str(response.mimetype or "").startswith("text/html"):
            return response
        # Targeted exact-row refreshes return fragments and must stay inert.
        if request.headers.get("X-BT38-UI-Refresh") == "targeted":
            return response
        html = _strip_feature_assets(response.get_data(as_text=True))
        if "bt38FbmLazyFeatureBoundary" not in html:
            html = html.replace("</body>", _BOOTSTRAP + "</body>", 1) if "</body>" in html else html + _BOOTSTRAP
        response.set_data(html)
        response.content_length = len(response.get_data())
        return response

    app._bt38_fbm_lazy_startup_alignment_installed = True
