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
    assert 'if updates or service_persisted:\n        db.session.commit()' in AMAZON_TRACKING
    assert 'if updates or shipment_persisted' not in AMAZON_TRACKING
    assert '_persist_marketplace_shipment(' not in AMAZON_TRACKING
    assert 'provider="marketplace"' not in AMAZON_TRACKING
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


def test_amazon_marketplace_journey_reuses_existing_fbm_projection_without_proxy_shipment():
    assert 'shipment_confirmation_state(shipment) if shipment else "not_started"' in FBM_PAGE_ALIGNMENT
    assert '_page_alignment.render_template = _governed_render_template' in AMAZON_FBM_PROFILE_ALIGNMENT
    assert '"picked_up": "accepted"' in AMAZON_FBM_PROFILE_ALIGNMENT
    assert '"in_transit": "in_transit"' in AMAZON_FBM_PROFILE_ALIGNMENT
    assert '"out_for_delivery": "out_for_delivery"' in AMAZON_FBM_PROFILE_ALIGNMENT
    assert '"delivered": "delivered"' in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'item.get("shipment") is not None' in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'aligned["shipment_state"] = journey_state' in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'FBMShipment(' not in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'requests.' not in AMAZON_FBM_PROFILE_ALIGNMENT
    assert 'db.session.add(' not in AMAZON_FBM_PROFILE_ALIGNMENT


def test_ebay_exact_tracking_hydration_remains_existing_order_only():
    assert 'shipping_fulfillment' in EBAY_TRACKING
    assert 'MarketplaceOrder.query' in EBAY_TRACKING
    assert 'db.session.add(MarketplaceOrder' not in EBAY_TRACKING
    assert 'FBMShipment(' not in EBAY_TRACKING


def test_ebay_shipped_notification_refresh_uses_persisted_grant_scope_set():
    assert 'governed_ebay_refresh_scopes' in EBAY_SHIPPING_NOTIFICATION
    assert 'refresh_scopes = governed_ebay_refresh_scopes(creds)' in EBAY_SHIPPING_NOTIFICATION
    assert '"scope": refresh_scopes' in EBAY_SHIPPING_NOTIFICATION
