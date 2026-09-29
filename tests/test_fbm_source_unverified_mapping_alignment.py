from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "templates" / "fbm.html").read_text()
FALLBACK = (ROOT / "services" / "governed_fbm_unverified_fallback_alignment.py").read_text()
PROMISE = (ROOT / "services" / "fbm_db_delivery_promise_alignment.py").read_text()
AUTHORITY = (ROOT / "services" / "governed_fbm_marketplace_dispatch_authority_alignment.py").read_text()


def test_source_unverified_is_not_carrier_mapping():
    assert "source-unverified-mapping" not in TEMPLATE
    assert "Map this exact carrier/service" not in TEMPLATE
    assert '<span class="badge bg-secondary">Source unverified</span>' in TEMPLATE


def test_only_missing_cells_open_inline_fallback():
    assert "Source unverified" in TEMPLATE
    assert "Pending\\s*\\/\\s*unavailable" in TEMPLATE
    assert "!String(row.dataset.trackingNumber||'').trim()" in TEMPLATE
    assert "dblclick" in TEMPLATE
    assert "/unverified-options?field=" in TEMPLATE
    assert "/unverified-field" in TEMPLATE


def test_tracking_is_exact_order_completion_not_mapping():
    assert 'if field == "tracking":' in FALLBACK
    assert "order.tracking_number = value" in FALLBACK
    assert '"reusable_mapping": False' in FALLBACK


def test_cost_suggestions_are_quantity_specific_and_manual_entry_remains():
    assert "COALESCE(mo.quantity, 1) = :quantity" in FALLBACK
    assert "Or enter actual price" in TEMPLATE
    assert "manual_fallback" in FALLBACK


def test_manual_cost_yields_to_automatic_recovered_spend():
    assert "source <> 'manual_fallback'" in PROMISE
    assert "NOT EXISTS" in PROMISE
    assert "automatic.source <> 'manual_fallback'" in PROMISE


def test_manual_source_remains_below_real_physical_provider_truth():
    assert 'provider", "") or "").strip().lower() == "marketplace"' in AUTHORITY
    assert 'label_source", "") or "").strip()' in AUTHORITY
    assert "if key in result" in AUTHORITY
