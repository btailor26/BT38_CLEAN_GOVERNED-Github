from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_fbm_mcf_display_is_badge_and_persisted_price_only():
    page = (ROOT / "services" / "governed_fbm_page_alignment.py").read_text()
    template = (ROOT / "templates" / "fbm.html").read_text()

    assert "joinedload(MarketplaceOrder.mcf_order)" in page
    assert '"source_label": "Amazon MCF"' in page
    assert '"shipping_cost": row.mcf_order.total_mcf_fee' in page
    assert '"currency": row.mcf_order.currency or "GBP"' in page

    assert "{% if mcf_display %}" in template
    assert "{{ mcf_display.source_label }}" in template
    assert "mcf_display.shipping_cost" in template


def test_fbm_mcf_display_does_not_take_shipment_lifecycle_authority():
    page = (ROOT / "services" / "governed_fbm_page_alignment.py").read_text()
    template = (ROOT / "templates" / "fbm.html").read_text()

    assert "Display-only MCF identity/cost. Shipment lifecycle authority stays unchanged." in page
    assert "{% set tracking_number = shipment.tracking_number if shipment and shipment.tracking_number else order.tracking_number %}" in template
    assert "{% set carrier_name = shipment.carrier if shipment and shipment.carrier else order.carrier %}" in template
    assert "mcf_display.tracking" not in template
    assert "mcf_display.carrier" not in template
