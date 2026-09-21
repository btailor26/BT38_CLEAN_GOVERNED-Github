from app import app

from governed_mcf_routes import governed_mcf_bp

if "governed_mcf" not in app.blueprints:
    app.register_blueprint(governed_mcf_bp)

import services.governed_mcf_compat  # noqa: F401
import services.governed_ui_event_signal  # noqa: F401
import services.governed_webhook_rejection_recovery  # noqa: F401
import services.governed_ebay_shipping_notification_registration_alignment  # noqa: F401

# Web import must stay side-effect free. eBay post-deploy alignment is an
# explicit deployment/recovery operation and must never run while Gunicorn is
# importing main:app. Blocking DB/marketplace recovery here can prevent even
# /login from being served and duplicates the governed runtime boundary.
import services.governed_ebay_order_identity_alignment  # noqa: F401
import services.governed_fbm_shipment_event_alignment  # noqa: F401
import services.auth_session_legacy_cleanup  # noqa: F401
import services.public_early_access  # noqa: F401
import services.account_profile_alignment  # noqa: F401
import services.package_catalog_alignment  # noqa: F401
from services.governed_customer_behaviour_recorder import install_governed_customer_behaviour_recorder
from services.governed_notification_read_alignment import install_governed_notification_read_alignment
from services.governed_fbm_page_alignment import install_governed_fbm_page_alignment
from services.governed_fbm_shipment_selection_alignment import install_governed_fbm_shipment_selection_alignment
from services.governed_fbm_marketplace_dispatch_authority_alignment import install_governed_fbm_marketplace_dispatch_authority_alignment
from services.fbm_db_delivery_promise_alignment import install_fbm_db_delivery_promise_alignment
from services.governed_fbm_global_search_alignment import install_governed_fbm_global_search_alignment
from services.governed_fbm_local_controls_alignment import install_governed_fbm_local_controls_alignment
from services.governed_fbm_render_budget_alignment import install_governed_fbm_render_budget_alignment
from services.governed_fbm_dispatch_queue_alignment import install_governed_fbm_dispatch_queue_alignment
from services.governed_fbm_browser_session_authority_alignment import install_governed_fbm_browser_session_authority_alignment
from services.governed_fbm_exact_record_session_alignment import install_governed_fbm_exact_record_session_alignment
from services.governed_product_linking_unlink_alignment import install_product_linking_unlink_alignment
from services.governed_ebay_native_shipping_alignment import install_governed_ebay_native_shipping_alignment
from services.governed_ebay_shipping_connection_ui_alignment import install_governed_ebay_shipping_connection_ui_alignment
from services.governed_ebay_packlink_confirmation_alignment import install_governed_ebay_packlink_confirmation_alignment
from services.governed_fbm_db_authority_alignment import install_governed_fbm_db_authority_alignment
from services.governed_shipping_spend_alignment import install_governed_shipping_spend_alignment
from services.governed_shipping_spend_reporting import install_governed_shipping_spend_reporting
from services.governed_seller_delivery_config import install_governed_seller_delivery_config
from services.governed_sds_fbm_read_alignment import install_governed_sds_fbm_read_alignment
from services.governed_sds_dispatch_alignment import install_governed_sds_dispatch_alignment
from services.governed_sds_label_alignment import install_governed_sds_label_alignment
from services.governed_sds_scan_alignment import install_governed_sds_scan_alignment
from services.governed_sds_scanner_lookup_alignment import install_governed_sds_scanner_lookup_alignment
from services.governed_warehouse_inbound_installer import install as install_governed_warehouse_inbound
from services.governed_ebay_return_intake_alignment import install_governed_ebay_return_intake_alignment
from services.governed_fbm_small_alignment import (
    install_governed_fbm_small_alignment,
)
from services.governed_fbm_ready_landing_alignment import install_governed_fbm_ready_landing_alignment
from services.governed_exact_record_event_alignment import install_governed_exact_record_event_alignment
from services.governed_bell_event_projection_alignment import install_governed_bell_event_projection_alignment
from services.governed_webhook_bell_event_alignment import install_governed_webhook_bell_event_alignment
from services.governed_amazon_fbm_profile_event_alignment import install_governed_amazon_fbm_profile_event_alignment
from services.governed_fbm_current_amazon_profile_alignment import install_governed_fbm_current_amazon_profile_alignment
from services.governed_fbm_tracking_authority_restore import install_governed_fbm_tracking_authority_restore
from services.governed_fbm_parcel_grouping_alignment import install_governed_fbm_parcel_grouping_alignment
from services.governed_fbm_shared_shipment_confirmation_alignment import install_governed_fbm_shared_shipment_confirmation_alignment
from services.governed_fbm_replacement_label_alignment import install_governed_fbm_replacement_label_alignment
from services.governed_fbm_order_projection_alignment import install_governed_fbm_order_projection_alignment
from services.governed_royal_mail_click_drop_alignment import install_governed_royal_mail_click_drop_alignment

install_governed_customer_behaviour_recorder(app)
install_governed_notification_read_alignment(app)
install_governed_fbm_page_alignment(app)
install_governed_fbm_shipment_selection_alignment(app)
install_governed_fbm_marketplace_dispatch_authority_alignment()
install_governed_fbm_order_projection_alignment()
install_fbm_db_delivery_promise_alignment(app)
install_governed_fbm_global_search_alignment(app)
install_governed_fbm_local_controls_alignment(app)
install_governed_fbm_render_budget_alignment(app)

# Dispatch owns lifecycle classification. The final browser-session authority
# owns the bounded FBM row set and Health shell so History + lifecycle + Health
# consume one rendered session. The old all-orders Health snapshot installer is
# intentionally not installed because it creates a second DB/session authority.
install_governed_fbm_dispatch_queue_alignment(app)
import services.governed_fbm_history_controls_alignment  # noqa: F401,E402
install_governed_fbm_browser_session_authority_alignment(app)

import services.governed_fbm_fba_visibility_alignment  # noqa: F401,E402
install_product_linking_unlink_alignment(app)
install_governed_ebay_native_shipping_alignment(app)
install_governed_ebay_shipping_connection_ui_alignment(app)
install_governed_ebay_packlink_confirmation_alignment()
install_governed_fbm_db_authority_alignment()
install_governed_shipping_spend_alignment(app)
install_governed_shipping_spend_reporting(app)
install_governed_seller_delivery_config(app)
install_governed_sds_fbm_read_alignment()
install_governed_sds_dispatch_alignment(app)
install_governed_sds_label_alignment(app)
install_governed_sds_scan_alignment(app)
install_governed_sds_scanner_lookup_alignment(app)
install_governed_warehouse_inbound(app)
install_governed_ebay_return_intake_alignment()
install_governed_fbm_small_alignment(app)
install_governed_fbm_ready_landing_alignment(app)
install_governed_fbm_parcel_grouping_alignment(app)
install_governed_fbm_shared_shipment_confirmation_alignment()
install_governed_fbm_replacement_label_alignment(app)
install_governed_royal_mail_click_drop_alignment(app)
install_governed_amazon_fbm_profile_event_alignment(app)
install_governed_webhook_bell_event_alignment(app)
install_governed_exact_record_event_alignment(app)
install_governed_bell_event_projection_alignment(app)
install_governed_fbm_tracking_authority_restore(app)

# Final Bell contract: presentation only. It mirrors the current FBM browser
# session and must not query DB/marketplace/carrier state or introduce polling.
install_governed_fbm_bell_display_only_alignment(app)

# Final FBM event boundary: an exact committed order event mutates only that
# browser-session record. It must run after legacy refresh installers so the old
# full /fbm GET/rebuild path cannot fire for the same event.
install_governed_fbm_exact_record_session_alignment(app)

from services.governed_ebay_notification_challenge import install_ebay_notification_challenge_handler
install_ebay_notification_challenge_handler(app)


@app.after_request
def acknowledge_captured_ebay_webhook(response):
    """Acknowledge eBay once its notification is durably captured."""
    from flask import request
    if request.method != "POST":
        return response
    if request.path.rstrip("/") != "/governed/webhooks/ebay":
        return response
    if response.status_code < 500:
        return response
    payload = response.get_json(silent=True)
    if not isinstance(payload, dict):
        return response
    if payload.get("status") != "processing_failed":
        return response
    if payload.get("notification_record_id") is None:
        return response
    response.status_code = 200
    response.headers["X-BT38-Webhook-Capture"] = "stored"
    response.headers["X-BT38-Webhook-Processing"] = "failed-after-capture"
    return response

