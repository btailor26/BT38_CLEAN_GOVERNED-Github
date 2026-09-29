from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "templates" / "fbm.html").read_text()
MAPPING = (ROOT / "services" / "fbm_carrier_mapping.py").read_text()
ROUTES = (ROOT / "governed_fbm_routes.py").read_text()
FALLBACK = (ROOT / "services" / "governed_fbm_unverified_fallback_alignment.py").read_text()
PROMISE = (ROOT / "services" / "fbm_db_delivery_promise_alignment.py").read_text()
AUTHORITY = (ROOT / "services" / "governed_fbm_marketplace_dispatch_authority_alignment.py").read_text()


def test_source_unverified_is_not_carrier_mapping():
    assert "source-unverified-mapping" not in TEMPLATE
    assert "Map this exact carrier/service" not in TEMPLATE
    assert '<span class="badge bg-secondary">Source unverified</span>' in TEMPLATE


def test_mapping_is_one_governed_review_flow_not_per_order_editor():
    assert "save-inline-mapping" not in TEMPLATE
    assert "mapping-editor" not in TEMPLATE
    assert "function mappingEditor" not in TEMPLATE
    assert "function saveMapping" not in TEMPLATE
    assert 'id="fbmMappingReviewModal"' in TEMPLATE
    assert "/fbm/mappings/pending" in TEMPLATE
    assert "/fbm/carrier-mappings/" in TEMPLATE
    assert "Verify exact mapping" in TEMPLATE


def test_exact_mapping_authority_is_reused_and_review_is_existing_db_authority():
    assert "def find_mapping(" in MAPPING
    assert "def ensure_mapping_review(" in MAPPING
    assert "FBMCarrierServiceMapping.query.filter_by(**key).first()" in MAPPING
    assert 'verification_status="pending_review"' in MAPPING
    assert 'mapping.verification_status == "verified"' in MAPPING
    assert "FBMShipmentMappingReview.query.filter_by(shipment_id=shipment.id).first()" in MAPPING
    assert '@governed_fbm_bp.get("/fbm/mappings/pending")' in ROUTES
    assert '@governed_fbm_bp.post("/fbm/carrier-mappings/<int:mapping_id>/verify")' in ROUTES


def test_only_missing_cells_open_inline_fallback():
    assert "Pending\\s*\\/\\s*unavailable" in TEMPLATE
    assert "!String(row.dataset.trackingNumber||'').trim()" in TEMPLATE
    assert "dblclick" in TEMPLATE
    assert "/unverified-options?field=" in TEMPLATE
    assert "/unverified-field" in TEMPLATE


def test_tracking_is_exact_order_completion_not_mapping():
    assert 'if field == "tracking":' in FALLBACK
    assert "order.tracking_number = value" in FALLBACK
    assert '"reusable_mapping": False' in FALLBACK


def test_manual_cost_yields_to_automatic_recovered_spend():
    assert "source <> 'manual_fallback'" in PROMISE
    assert "NOT EXISTS" in PROMISE
    assert "automatic.source <> 'manual_fallback'" in PROMISE


def test_manual_source_remains_below_real_physical_provider_truth():
    assert 'provider", "") or "").strip().lower() == "marketplace"' in AUTHORITY
    assert 'label_source", "") or "").strip()' in AUTHORITY
    assert "if key in result" in AUTHORITY
