from services.governed_order_clarity_alignment import _align_fbm_recommended_shipping_html


def test_shipping_cell_replaces_generic_route_badges_with_recommended_shipping_action():
    html = '''
    <table><tbody>
      <tr class="fbm-order-row" data-order-id="123">
        <td class="fbm-route-cell">
          <div class="small text-muted">Marketplace promise</div><strong>UK_RoyalMail48</strong>
          <div class="small mt-1"><span class="badge bg-primary me-1">Marketplace</span><span class="badge bg-light text-dark border me-1">Packlink / carrier</span><span class="badge bg-light text-dark border">Manual</span></div>
          <div class="fbm-row-note text-muted">Route: eBay Shipping</div>
        </td>
        <td>Other</td>
      </tr>
    </tbody></table>
    '''

    aligned = _align_fbm_recommended_shipping_html(html)

    assert "Marketplace promise" in aligned
    assert "UK_RoyalMail48" in aligned
    assert "Recommended shipping" in aligned
    assert 'class="btn btn-sm btn-outline-primary fbm-shipping-options mt-1"' in aligned
    assert 'data-order-id="123"' in aligned
    assert "Marketplace</span>" not in aligned
    assert "Packlink / carrier" not in aligned
    assert ">Manual</span>" not in aligned
    assert "Route: eBay Shipping" not in aligned
    assert "BT38 never guesses a cutoff time" in aligned


def test_shipping_cell_does_not_invent_missing_marketplace_promise():
    html = '''
    <table><tbody>
      <tr class="fbm-order-row" data-order-id="456">
        <td class="fbm-route-cell"><strong>Packlink / connected carrier</strong></td>
        <td>Other</td>
      </tr>
    </tbody></table>
    '''

    aligned = _align_fbm_recommended_shipping_html(html)

    assert "Marketplace promise" in aligned
    assert "Pending" in aligned
    assert "Packlink / connected carrier" not in aligned
    assert "Recommended shipping" in aligned
