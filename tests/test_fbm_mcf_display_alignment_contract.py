from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_fbm_mcf_display_uses_persisted_identity_cost_and_breakdown():
    page = (ROOT / "services" / "governed_fbm_page_alignment.py").read_text()
    template = (ROOT / "templates" / "fbm.html").read_text()

    assert "joinedload(MarketplaceOrder.mcf_order)" in page
    assert '"source_label": "Amazon MCF"' in page
    assert '"shipping_fee": row.mcf_order.mcf_fulfillment_fee' in page
    assert '"shipping_cost": row.mcf_order.mcf_per_shipment_fee' in page
    assert '"currency": row.mcf_order.currency or "GBP"' in page

    assert "{% if mcf_display %}" in template
    assert "{{ mcf_display.source_label }}" in template
    assert "<th>Shipping Fee</th>" in template
    assert 'class="fbm-shipping-fee-cell"' in template
    assert '<td class="fbm-shipping-cost-cell">' in template

    fee_cell = template.split('<td class="fbm-shipping-fee-cell">', 1)[1].split("</td>", 1)[0]
    cost_cell = template.split('<td class="fbm-shipping-cost-cell">', 1)[1].split("</td>", 1)[0]
    assert "mcf_display.shipping_fee" in fee_cell
    assert "shipping.get('shipping_cost')" not in fee_cell
    assert "mcf_display.shipping_fee" not in cost_cell
    assert "mcf_display.shipping_cost" in cost_cell
    assert "shipping.get('shipping_cost')" in cost_cell

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


def test_fbm_has_mcf_only_fee_before_single_shipping_cost_column():
    template = (ROOT / "templates" / "fbm.html").read_text()
    header = template.split('<table class="table table-hover align-middle mb-0 fbm-orders-table">', 1)[1].split("</thead>", 1)[0]
    row = template.split('<tr class="fbm-order-row"', 1)[1].split("</tr>", 1)[0]

    assert header.count("<th>Shipping Fee</th>") == 1
    assert header.count("<th>Shipping Cost</th>") == 1
    assert header.index("<th>Shipping Fee</th>") < header.index("<th>Shipping Cost</th>")
    assert row.count('class="fbm-shipping-fee-cell"') == 1
    assert row.count('class="fbm-shipping-cost-cell"') == 1
    assert 'colspan="12" class="text-center text-muted py-5"' in template

    fee_cell = row.split('<td class="fbm-shipping-fee-cell">', 1)[1].split("</td>", 1)[0]
    assert "mcf_display.shipping_fee" in fee_cell
    assert "shipping.get('shipping_cost')" not in fee_cell
