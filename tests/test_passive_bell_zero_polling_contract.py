from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INIT = (ROOT / "services" / "__init__.py").read_text()
BELL = (ROOT / "services" / "governed_bell_event_projection_alignment.py").read_text()
FBM_AMAZON = (ROOT / "services" / "governed_fbm_current_amazon_profile_alignment.py").read_text()


def test_bell_uses_existing_fbm_projection_not_passive_override():
    assert "import services.governed_passive_bell_alignment" not in INIT
    assert "function fbmRowFor(orderId)" in BELL
    assert "function fbmProjection(detail)" in BELL
    assert "notification_source:'fbm_page'" in BELL


def test_bell_projection_is_zero_polling_and_zero_authority_reads():
    assert "setInterval" not in BELL
    assert "XMLHttpRequest" not in BELL
    assert "db.session" not in BELL
    assert "MarketplaceOrder.query" not in BELL
    assert "FBMShipment.query" not in BELL
    assert "requests." not in BELL
    assert "window.addEventListener('bt38-marketplace-event'" in BELL
    assert "function fbmProjection(detail)" in BELL


def test_fbm_page_has_no_page_time_marketplace_hydration():
    assert "def _hydrate_current_missing_profiles" in FBM_AMAZON
    assert "return None" in FBM_AMAZON
    forbidden = (
        "get_or_refresh_amazon_profile",
        "AmazonOrderProfileError",
        "@app.before_request",
        "requests.",
    )
    for token in forbidden:
        assert token not in FBM_AMAZON


def test_main_has_one_final_bell_projection_authority():
    main = (ROOT / "main.py").read_text()
    assert main.count("install_governed_bell_event_projection_alignment(app)") == 1
    assert "install_governed_fbm_bell_display_only_alignment(app)" not in main
