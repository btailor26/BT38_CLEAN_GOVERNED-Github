from pathlib import Path


ROUTES = Path("governed_fbm_routes.py").read_text(encoding="utf-8")
CLARITY = Path("services/governed_order_clarity_alignment.py").read_text(encoding="utf-8")
TEMPLATE = Path("templates/fbm.html").read_text(encoding="utf-8")


def test_fbm_page_is_db_only_and_provider_reads_stay_on_explicit_shipping_actions():
    assert "Page GETs must\nnot recover, reconcile, hydrate, or call marketplace/provider APIs." in CLARITY
    assert "_inject_db_delivery_truth" in CLARITY
    assert "PacklinkAdapter" not in CLARITY
    assert "FBMRateQuote" not in CLARITY
    assert "urlopen(" not in CLARITY
    assert "setInterval(" not in CLARITY

    assert '@governed_fbm_bp.get("/fbm")' in ROUTES
    assert '@governed_fbm_bp.post("/fbm/orders/<int:order_id>/packlink/rates")' in ROUTES
    assert "PacklinkAdapter().get_rates(order=order, parcel=parcel)" in ROUTES


def test_shipping_options_are_explicit_and_do_not_turn_page_load_into_rate_fetch():
    assert "Shipping options" in TEMPLATE
    assert 'class="btn btn-sm btn-outline-primary fbm-shipping-options"' in TEMPLATE
    assert '@governed_fbm_bp.get("/fbm/shipping-options")' in ROUTES
    assert "_shipping_provider_options(row, profile, profile_error)" in ROUTES
    assert "Packlink PRO live rates and shipment drafting are connected" in ROUTES


def test_packlink_rates_are_persisted_once_and_reused_by_exact_quote_identity():
    assert "rates = PacklinkAdapter().get_rates(order=order, parcel=parcel)" in ROUTES
    assert "FBMRateQuote(" in ROUTES
    assert "expires_at=datetime.utcnow() + timedelta(minutes=15)" in ROUTES
    assert "quote_id" in ROUTES
    assert "quote = db.session.get(FBMRateQuote, quote_id)" in ROUTES
    assert "Packlink rate quote does not belong to this order." in ROUTES
    assert "Packlink rate quote expired. Get fresh rates." in ROUTES


def test_packlink_draft_requires_explicit_confirmation_and_selected_saved_rate():
    assert 'body.get("confirm_create") != "CREATE_PACKLINK_DRAFT"' in ROUTES
    assert "Explicit CREATE_PACKLINK_DRAFT confirmation is required." in ROUTES
    assert "selected = _find_rate(quote, rate_id)" in ROUTES
    assert "Selected Packlink service is not in the stored quote." in ROUTES
    assert "awaiting_provider_payment" in ROUTES
    assert '"label_ready": False' in ROUTES


def test_prime_sfp_never_falls_through_to_external_shipping():
    assert "Prime/SFP orders must use Amazon Buy Shipping." in ROUTES
    assert '"prime_locked": is_prime' in ROUTES
    assert "external_allowed = platform != \"amazon\" or not is_prime" in ROUTES
    assert "manual_allowed = platform != \"amazon\" or not is_prime" in ROUTES
