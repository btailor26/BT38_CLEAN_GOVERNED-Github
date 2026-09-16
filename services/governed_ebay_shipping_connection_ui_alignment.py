"""Expose eBay native shipping as an explicit Shipping Connection.

Store connection remains store/order/listing authority. This surface only checks
whether an already-connected eBay seller can authorize the separate native
shipping capability used by BT38's eBay Shipping provider. It does not register,
modify, or consume sale/dispatch webhooks.
"""
from __future__ import annotations

from flask import jsonify
from flask_login import login_required

from models import Store
from services import governed_fbm_page_alignment as _page
from services.governed_ebay_native_shipping_alignment import (
    EBAY_LOGISTICS_SCOPE,
    EbayNativeShippingError,
    _access_token,
)

_INSTALLED = False


def _ebay_shipping_card() -> str:
    return (
        '<div class="border rounded p-2" id="ebayShippingConnectionCard">'
        '<div class="d-flex justify-content-between align-items-center gap-2">'
        '<div class="d-flex align-items-center gap-2">'
        '<img src="/static/img/marketplaces/ebay.png" alt="eBay" title="eBay Shipping" '
        'style="width:58px;max-height:28px;object-fit:contain">'
        '<div><strong>eBay Shipping</strong>'
        '<div class="small text-muted">Separate shipping authorization for eBay native rates and labels.</div></div>'
        '</div>'
        '<button id="ebayShippingConnectionTest" class="btn btn-sm btn-outline-primary" type="button">Test connection</button>'
        '</div>'
        '<div id="ebayShippingConnectionStatus" class="small text-muted mt-2">'
        'Store connection is separate. Test only the eBay Shipping authorization here.'
        '</div>'
        '</div>'
    )


def _shipping_connection_script() -> str:
    return '''<script id="bt38EbayShippingConnectionUI">
(function(){
  var button=document.getElementById('ebayShippingConnectionTest');
  var status=document.getElementById('ebayShippingConnectionStatus');
  if(!button||!status)return;
  button.addEventListener('click',async function(){
    button.disabled=true;
    status.className='small text-muted mt-2';
    status.textContent='Testing eBay Shipping authorization…';
    try{
      var response=await fetch('/fbm/shipping-connections/ebay/status',{credentials:'same-origin',cache:'no-store',headers:{'Accept':'application/json'}});
      var payload=await response.json().catch(function(){return {};});
      if(!response.ok||payload.success!==true)throw new Error(payload.message||('HTTP '+response.status));
      status.className='small text-success mt-2';
      status.textContent=payload.message;
    }catch(error){
      status.className='small text-danger mt-2';
      status.textContent=error.message;
    }finally{button.disabled=false;}
  });
})();
</script>'''


def install_governed_ebay_shipping_connection_ui_alignment(app) -> None:
    """Add eBay beside existing Shipping setup without touching webhook authority."""
    global _INSTALLED
    if _INSTALLED:
        return

    original_setup_html = _page._setup_html

    def aligned_setup_html() -> str:
        html = original_setup_html()
        html = html.replace(
            '<summary><strong>Shipping setup</strong><span>Packlink PRO · Label printer</span></summary>',
            '<summary><strong>Shipping connections</strong><span>eBay Shipping · Packlink PRO · Label printer</span></summary>',
            1,
        )
        marker = '</div></details>'
        if marker in html:
            html = html.replace(marker, _ebay_shipping_card() + marker, 1)
        return html + _shipping_connection_script()

    _page._setup_html = aligned_setup_html

    @login_required
    def ebay_shipping_connection_status():
        stores = (
            Store.query
            .filter(Store.is_active.is_(True))
            .order_by(Store.id.asc())
            .all()
        )
        ebay_stores = [
            store for store in stores
            if str(getattr(store, 'platform', '') or '').strip().lower() == 'ebay'
        ]
        if not ebay_stores:
            return jsonify({
                'success': False,
                'message': 'Connect an eBay store first, then authorize eBay Shipping here.',
                'shipping_connection': True,
                'webhook_authority_changed': False,
            }), 404

        ready = []
        blocked = []
        for store in ebay_stores:
            try:
                _access_token(store)
                ready.append({'store_id': store.id, 'store_name': store.name})
            except EbayNativeShippingError as exc:
                blocked.append({
                    'store_id': store.id,
                    'store_name': store.name,
                    'authorization_required': bool(exc.authorization_required),
                    'limited_release_required': bool(exc.limited_release_required),
                    'message': str(exc),
                })

        if ready:
            names = ', '.join(str(row['store_name'] or row['store_id']) for row in ready)
            return jsonify({
                'success': True,
                'shipping_connection': True,
                'required_scope': EBAY_LOGISTICS_SCOPE,
                'stores': ready,
                'blocked_stores': blocked,
                'webhook_authority_changed': False,
                'message': f'eBay Shipping authorization is available for {names}. Open an eBay order and request rates to test Logistics API access.',
            })

        first = blocked[0] if blocked else {}
        return jsonify({
            'success': False,
            'shipping_connection': True,
            'required_scope': EBAY_LOGISTICS_SCOPE,
            'stores': [],
            'blocked_stores': blocked,
            'webhook_authority_changed': False,
            'message': first.get('message') or 'eBay Shipping authorization is not available for the connected eBay store.',
        }), 403

    app.add_url_rule(
        '/fbm/shipping-connections/ebay/status',
        endpoint='bt38_ebay_shipping_connection_status',
        view_func=ebay_shipping_connection_status,
        methods=['GET'],
    )
    _INSTALLED = True
