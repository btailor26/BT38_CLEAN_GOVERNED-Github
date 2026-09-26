from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = (ROOT / "services" / "fbm_packlink_adapter.py").read_text(encoding="utf-8")
ROUTES = (ROOT / "governed_fbm_routes.py").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "templates" / "fbm.html").read_text(encoding="utf-8")
SPEND = (ROOT / "services" / "governed_shipping_spend_alignment.py").read_text(encoding="utf-8")


def test_packlink_recovery_discovers_only_exact_marketplace_reference():
    assert "def find_shipment_by_custom_reference" in ADAPTER
    assert 'row_custom != wanted' in ADAPTER
    assert 'query={"inbox": inbox}' in ADAPTER
    assert "multiple shipments for this exact marketplace order" in ADAPTER


def test_packlink_recovery_is_explicit_and_never_writes_marketplace():
    assert '@governed_fbm_bp.post("/fbm/shipments/<int:shipment_id>/packlink/recover")' in ROUTES
    assert 'shipment.provider = "packlink"' in ROUTES
    assert "reconcile_packlink_tracking_lifecycle(" in ROUTES
    assert '"marketplace_write_attempted": False' in ROUTES
    recovery = ROUTES.split("def packlink_exact_recovery", 1)[1].split('@governed_fbm_bp.get("/fbm/shipments/', 1)[0]
    assert "confirm_external_shipment" not in recovery
    assert "persist_external_label" not in recovery


def test_packlink_provider_price_is_persisted_from_provider_truth():
    assert "def recover_packlink_provider_spend" in SPEND
    assert 'price.get("total_price")' in SPEND
    assert 'source="packlink_provider_purchase"' in SPEND


def test_amazon_recovery_uses_packlink_only_as_missing_truth_fallback():
    assert "Number(h.tracking_events_persisted||0)===0||cost.shipping_cost===null||cost.shipping_cost===undefined" in TEMPLATE
    assert "/packlink/recover" in TEMPLATE
    assert "source Packlink" in TEMPLATE
    assert "marketplace write" in TEMPLATE
