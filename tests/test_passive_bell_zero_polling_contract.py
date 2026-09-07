from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "services" / "governed_passive_bell_alignment.py").read_text()
INIT = (ROOT / "services" / "__init__.py").read_text()


def test_passive_bell_is_installed():
    assert "import services.governed_passive_bell_alignment" in INIT
    assert "ready._event_only_bell_reader = passive_event_only_bell_reader" in SOURCE


def test_passive_bell_has_no_persistent_or_external_authority_reads():
    forbidden = (
        "from extensions import db",
        "MarketplaceOrder",
        "FBMShipment",
        "MarketplaceListing",
        "WarehouseStock",
        "requests.",
        "PacklinkAdapter",
        "_ebay_access_token",
        "AmazonSPAPIAdapter",
    )
    for token in forbidden:
        assert token not in SOURCE


def test_passive_bell_is_zero_polling_and_recovery_silent():
    assert '"database_calls": False' in SOURCE
    assert '"marketplace_calls": False' in SOURCE
    assert '"provider_calls": False' in SOURCE
    assert '"polling": False' in SOURCE
    assert '"recovery_started": False' in SOURCE
    assert '"recovery", "hydrate", "hydration", "readback", "scan"' in SOURCE
    assert '"Get ready to dispatch"' in SOURCE


def test_passive_bell_dedupes_logical_movement_not_event_revision():
    assert "def _logical_key(record: dict)" in SOURCE
    assert "record.get(\"order_id\")" in SOURCE
    assert "record.get(\"sku\")" in SOURCE
    assert "record.get(\"status_label\")" in SOURCE
    assert "if key in seen:" in SOURCE
