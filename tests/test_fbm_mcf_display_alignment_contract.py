from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_fbm_mcf_display_uses_persisted_identity_cost_and_breakdown():
    page = (ROOT / "services" / "governed_fbm_page_alignment.py").read_text()
    template = (ROOT / "templates" / "fbm.html").read_text()

    assert "joinedload(MarketplaceOrder.mcf_order)" in page
    assert '"source_label": "Amazon MCF"' in page
    assert '"shipping_cost": row.mcf_order.total_mcf_fee' in page
    assert '"currency": row.mcf_order.currency or "GBP"' in page
    assert '"quantity": sum((item.quantity or 0)' in page
    assert '"fulfillment_fee": row.mcf_order.mcf_fulfillment_fee' in page
    assert '"first_unit_fee": sum((item.mcf_first_unit_fee or 0)' in page
    assert '"additional_unit_fee": sum((item.mcf_additional_unit_fee or 0)' in page

    assert "{% if mcf_display %}" in template
    assert "{{ mcf_display.source_label }}" in template
    assert "<th>Shipping cost</th>" in template
    assert '<td class="fbm-shipping-cost-cell">' in template
    assert "mcf_display.shipping_cost" in template
    assert "Picking total" in template

    # MCF identity stays in Shipping; its price belongs only in the dedicated cost cell.
    route_cell = template.split('<td class="fbm-route-cell">', 1)[1].split("</td>", 1)[0]
    cost_cell = template.split('<td class="fbm-shipping-cost-cell">', 1)[1].split("</td>", 1)[0]
    assert "{{ mcf_display.source_label }}" in route_cell
    assert "mcf_display.shipping_cost" not in route_cell
    assert "mcf_display.shipping_cost" in cost_cell
    assert "mcf_display.quantity" in cost_cell
    assert "Picking total" in cost_cell


def test_fbm_mcf_carrier_tracking_authority_is_marketplace_then_mcf_fallback():
    page = (ROOT / "services" / "governed_fbm_page_alignment.py").read_text()
    template = (ROOT / "templates" / "fbm.html").read_text()

    assert "Shipment lifecycle authority stays unchanged." in page
    assert '"fallback_carrier": row.mcf_order.carrier' in page
    assert '"fallback_tracking": row.mcf_order.tracking_number' in page
    assert "shipment.tracking_number if shipment and shipment.tracking_number else (mcf_display.fallback_tracking" in template
    assert "shipment.carrier if shipment and shipment.carrier else (mcf_display.fallback_carrier" in template

    # A linked MCF row must never fall straight through to stale marketplace_orders.carrier.
    assert "{% set carrier_name = shipment.carrier if shipment and shipment.carrier else order.carrier %}" not in template


def test_fbm_shipping_cost_display_tolerates_missing_optional_cost_keys():
    template = (ROOT / "templates" / "fbm.html").read_text()
    cost_cell = template.split('<td class="fbm-shipping-cost-cell">', 1)[1].split("</td>", 1)[0]

    assert "shipping.get('shipping_cost') is not none" in cost_cell
    assert "shipping.get('shipping_cost_currency')" in cost_cell
    assert "shipping.shipping_cost is not none" not in cost_cell
    assert "shipping.shipping_cost_currency" not in cost_cell
    assert "Pending / unavailable" in cost_cell
