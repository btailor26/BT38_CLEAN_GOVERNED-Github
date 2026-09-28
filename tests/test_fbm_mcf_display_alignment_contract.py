from pathlib import Path


def _text(path):
    return Path(path).read_text(encoding="utf-8")


def test_mcf_projection_keeps_persisted_cost_components_for_display_only():
    page = _text("services/governed_fbm_page_alignment.py")
    assert '"source_label": "Amazon MCF"' in page
    assert '"shipping_fee": row.mcf_order.mcf_fulfillment_fee' in page
    assert '"shipping_cost": row.mcf_order.mcf_per_shipment_fee' in page


def test_fbm_ui_has_one_shipping_cost_column_and_no_fee_column():
    template = _text("templates/fbm.html")
    header = template.split("<thead", 1)[1].split("</thead>", 1)[0]
    row = template.split('<tr class="fbm-order-row"', 1)[1].split("</tr>", 1)[0]
    assert header.count("<th>Shipping Cost</th>") == 1
    assert "Shipping Fee" not in header
    assert "Picking Fee" not in header
    assert row.count('class="fbm-shipping-cost-cell"') == 1
    assert 'class="fbm-shipping-fee-cell"' not in row
    assert 'colspan="11" class="text-center text-muted py-5"' in template


def test_mcf_shipping_cost_is_picking_plus_shipment_with_hover_breakdown():
    template = _text("templates/fbm.html")
    cost_cell = template.split('<td class="fbm-shipping-cost-cell">', 1)[1].split("</td>", 1)[0]
    assert "mcf_display.shipping_cost + mcf_picking_fee" in cost_cell
    assert "shipping.get('shipping_cost')" in cost_cell
    assert 'data-bs-toggle="tooltip"' in cost_cell
    assert "Shipping cost breakdown" in cost_cell
    assert "Picking fee:" in cost_cell
    assert "Shipment:" in cost_cell
    assert "Total:" in cost_cell
    assert 'title="' not in cost_cell


def test_fbm_row_data_uses_same_final_mcf_shipping_cost_as_visible_ui():
    template = _text("templates/fbm.html")
    row = template.split('<tr class="fbm-order-row"', 1)[1].split(">", 1)[0]
    assert "data-shipping-fee=" not in row
    assert "data-shipping-fee-currency=" not in row
    assert "mcf_display.shipping_cost + (mcf_display.shipping_fee if mcf_display.shipping_fee is not none else 0)" in row


def test_fbm_refresh_has_no_retired_shipping_fee_path():
    js = _text("static/js/fbm_tracking_journey.js")
    assert "'shippingFee'" not in js
    assert "'shippingFeeCurrency'" not in js
    assert "'shippingCost'" in js
    assert "'shippingCostCurrency'" in js
