from pathlib import Path


AMAZON_TRACKING = Path("services/governed_amazon_tracking_readback.py").read_text(encoding="utf-8")
AMAZON_TRACKING_RUNTIME = Path(
    "services/governed_amazon_tracking_runtime_alignment.py"
).read_text(encoding="utf-8")
AMAZON_FBM_PROFILE_ALIGNMENT = Path(
    "services/governed_fbm_amazon_profile_alignment.py"
).read_text(encoding="utf-8")
FBM_PAGE_ALIGNMENT = Path(
    "services/governed_fbm_page_alignment.py"
).read_text(encoding="utf-8")
SERVICES_INIT = Path("services/__init__.py").read_text(encoding="utf-8")
EBAY_TRACKING = Path("services/governed_exact_ebay_order_hydration.py").read_text(encoding="utf-8")
EBAY_SHIPPING_NOTIFICATION = Path(
    "services/governed_ebay_shipping_notification_alignment.py"
).read_text(encoding="utf-8")
FBM_TRACKING_LEGACY = Path("static/js/fbm_tracking_journey_legacy.js").read_text(encoding="utf-8")


def test_amazon_orders_2026_exact_tracking_read_is_present():
    assert '/orders/2026-01-01/orders/' in AMAZON_TRACKING
    assert '"includedData": "PACKAGES"' in AMAZON_TRACKING
    assert 'trackingNumber' in AMAZON_TRACKING
    assert 'carrier' in AMAZON_TRACKING
    assert 'shipTime' in AMAZON_TRACKING
    assert 'x-amz-access-token' in AMAZON_TRACKING


def test_amazon_dispatch_status_is_authority_without_tracking_dependency():
    assert 'def _order_lifecycle(' in AMAZON_TRACKING
    assert 'order_payload.get("orderStatus")' in AMAZON_TRACKING
    assert '"SHIPPED": "shipped"' in AMAZON_TRACKING
    assert '"DELIVERED": "delivered"' in AMAZON_TRACKING
    assert 'lifecycle_status = order_lifecycle' in AMAZON_TRACKING
    assert 'tracked = [row for row in packages if _text(row.get("trackingNumber"))]' in AMAZON_TRACKING
    assert 'if not tracked:\n        return None, None' not in AMAZON_TRACKING
    assert 'package.get("shipTime")' in AMAZON_TRACKING
    assert 'package.get("createdTime")' not in AMAZON_TRACKING
    assert 'lifecycle_status = shipment.get("lifecycle_status")' in AMAZON_TRACKING
    assert '_can_advance_lifecycle(getattr(row, "status", None), lifecycle_status)' in AMAZON_TRACKING


def test_amazon_tracking_is_fbm_only_and_corrects_marketplace_owned_package_truth():
    assert '{"FBA", "AFN", "MCF"}' in AMAZON_TRACKING
    assert 'startswith("mcf_")' in AMAZON_TRACKING
    assert '_text(getattr(row, "tracking_number", None)) != _text(shipment["tracking_number"])' in AMAZON_TRACKING
    assert '_text(getattr(row, "carrier", None)) != _text(shipment["carrier"])' in AMAZON_TRACKING
    assert 'getattr(row, "shipped_at", None) != shipment["shipped_at"]' in AMAZON_TRACKING
    assert '_can_advance_lifecycle(getattr(row, "status", None), lifecycle_status)' in AMAZON_TRACKING
    assert '"marketplace_write_started": False' in AMAZON_TRACKING
    assert 'requests.put(' not in AMAZON_TRACKING
    assert 'requests.patch(' not in AMAZON_TRACKING


def test_amazon_readback_only_commits_real_canonical_change():
    assert 'service_persisted = _persist_package_shipping_service(' in AMAZON_TRACKING
    assert 'if updates or service_persisted or marketplace_shipment_persisted or tracking_events_persisted:' in AMAZON_TRACKING
    assert 'def _ensure_marketplace_shipment(' in AMAZON_TRACKING
    assert 'shipment.provider = "marketplace"' in AMAZON_TRACKING
    assert 'shipment.tracking_number = tracking' in AMAZON_TRACKING
    assert 'marketplace_confirmation_status = "marketplace_authoritative"' in AMAZON_TRACKING
    assert 'row.updated_at = datetime.utcnow()' in AMAZON_TRACKING


def test_amazon_exact_order_verification_reuses_existing_tracking_readback():
    assert 'import services.governed_amazon_tracking_runtime_alignment' in SERVICES_INIT
    assert 'runtime._verify_exact_order = _aligned_verify_exact_order' in AMAZON_TRACKING_RUNTIME
    assert 'hydrate_amazon_tracking_for_order(' in AMAZON_TRACKING_RUNTIME
    assert 'marketplace_order_id=order_id' in AMAZON_TRACKING_RUNTIME
    assert 'marketplace not in {"amazon", "amazon_fbm"}' in AMAZON_TRACKING_RUNTIME
    assert 'threading.Thread' not in AMAZON_TRACKING_RUNTIME
    assert 'while ' not in AMAZON_TRACKING_RUNTIME
    assert 'MarketplaceOrder.query' not in AMAZON_TRACKING_RUNTIME
    assert 'FBMShipment(' not in AMAZON_TRACKING_RUNTIME
    assert 'requests.' not in AMAZON_TRACKING_RUNTIME


def test_fbm_amazon_page_render_is_event_only_and_has_no_marketplace_read():
    assert 'get_or_refresh_amazon_profile' not in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'hydrate_amazon_tracking_for_order' not in AMAZON_FBM_PROFILE_ALIGNMENT
    assert '_page_alignment._profile_map =' not in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'requests.' not in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'threading.Thread' not in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'while ' not in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'db.session' not in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'FBMShipment(' not in AMAZON_FBM_PROFILE_ALIGNMENT


def test_amazon_marketplace_journey_reuses_existing_fbm_projection_without_lifecycle_promotion():
    assert 'shipment_confirmation_state(shipment) if shipment else "not_started"' in FBM_PAGE_ALIGNMENT
    assert '_page_alignment.render_template = _governed_render_template' in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'aligned["shipment_state"] = journey_state' not in AMAZON_FBM_PROFILE_ALIGNMENT
    assert '"picked_up": "accepted"' not in AMAZON_FBM_PROFILE_ALIGNMENT
    assert '"delivered": "delivered"' not in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'FBMShipment(' not in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'requests.' not in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'db.session.add(' not in AMAZON_FBM_PROFILE_ALIGNMENT


def test_marketplace_tracking_click_reuses_existing_journey_modal_without_read_or_redirect():
    assert 'def _align_persisted_tracking_clicks(' in AMAZON_FBM_PROFILE_ALIGNMENT
    assert "platform not in {\"amazon\", \"ebay\"}" in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'fbm-tracking-journey' in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'data-journey-source="marketplace"' in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'data-platform=' in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'sellercentral.amazon.co.uk/orders-v3/order/' in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'ebay.co.uk/mesh/ord/details?orderid=' in AMAZON_FBM_PROFILE_ALIGNMENT
    assert "event.target.closest('.fbm-tracking-journey')" in FBM_TRACKING_LEGACY
    assert 'openJourney(journeyButton)' in FBM_TRACKING_LEGACY
    assert "document.getElementById('fbmTrackingJourneyModal')" in FBM_TRACKING_LEGACY
    assert "button.dataset.journeySource === 'marketplace'" in FBM_TRACKING_LEGACY
    assert 'fetch(' not in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'XMLHttpRequest' not in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'jsonFetch(' not in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'db.session' not in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'requests.' not in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'window.location' not in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'window.open(' not in AMAZON_FBM_PROFILE_ALIGNMENT


def test_ebay_exact_tracking_hydration_remains_existing_order_only():
    assert 'shipping_fulfillment' in EBAY_TRACKING
    assert 'MarketplaceOrder.query' in EBAY_TRACKING
    assert 'db.session.add(MarketplaceOrder' not in EBAY_TRACKING
    assert 'FBMShipment(' not in EBAY_TRACKING


def test_ebay_tracking_recovery_hydrates_complete_exact_order_truth():
    assert 'item.get("lineItemCost")' in EBAY_TRACKING
    assert 'row.quantity = exact_quantity' in EBAY_TRACKING
    assert 'row.unit_price = exact_unit_price' in EBAY_TRACKING
    assert 'row.line_total = exact_line_total' in EBAY_TRACKING
    assert 'row.shipping_charged = exact_order_shipping_charged' in EBAY_TRACKING
    assert '"line_economics_updates": line_economics_updates' in EBAY_TRACKING
    assert '"price_updates": price_updates' in EBAY_TRACKING
    assert '"marketplace_write_started": False' in EBAY_TRACKING


def test_ebay_shipped_notification_refresh_uses_persisted_grant_scope_set():
    assert 'governed_ebay_refresh_scopes' in EBAY_SHIPPING_NOTIFICATION
    assert 'refresh_scopes = governed_ebay_refresh_scopes(creds)' in EBAY_SHIPPING_NOTIFICATION
    assert '"scope": refresh_scopes' in EBAY_SHIPPING_NOTIFICATION


def test_exact_marketplace_recovery_contract_is_whole_journey_not_tracking_number_only():
    route = Path("services/governed_amazon_exact_order_recovery_route.py").read_text(encoding="utf-8")
    ebay_route = Path("services/governed_webhook_rejection_recovery.py").read_text(encoding="utf-8")

    # Amazon exact recovery already reads package event history and persists it
    # through the existing tracking ledger authority.
    assert "complete available persisted shipment journey" in route
    assert "hydrate_amazon_tracking_for_order(" in route
    assert "refresh_exact_amazon_order(row)" in route
    assert "hydrate_amazon_purchased_label_for_order(" in route
    assert "_persist_amazon_tracking_events(" in AMAZON_TRACKING
    assert "FBMShipmentTrackingEvent(" in AMAZON_TRACKING

    # eBay exact recovery must remain on its existing exact hydration/shipment
    # authorities rather than degrading Recovery to a missing-tracking action.
    assert "hydrate_exact_ebay_order(" in ebay_route
    assert "persist_exact_ebay_purchased_shipment_authority(" in ebay_route

    # Exact Recovery is finite/read-only against marketplaces.
    assert '"broad_scan_started": False' in route
    assert '"marketplace_write_started": False' in route
    assert '"marketplace_write_started": False' in ebay_route
