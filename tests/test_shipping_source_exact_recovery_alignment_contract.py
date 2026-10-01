from pathlib import Path


SOURCE = Path("services/governed_amazon_exact_order_recovery_route.py")


def test_packlink_shipping_gaps_follow_persisted_shipping_source():
    source = SOURCE.read_text(encoding="utf-8")

    assert 'shipping_source = str(shipment_truth.get("provider")' in source
    assert 'if shipping_source == "packlink" and shipping_gaps:' in source
    assert 'adapter.get_shipment(provider_reference)' in source
    assert 'adapter.get_tracking_status(reference=provider_reference)' in source
    assert 'recover_packlink_provider_spend(shipment, provider_payload)' in source
    assert 'recover_confirmed_packlink_spend(shipment)' in source
    assert 'reconcile_packlink_tracking_lifecycle(' in source


def test_packlink_branch_keeps_amazon_to_marketplace_owned_promises_only():
    source = SOURCE.read_text(encoding="utf-8")
    start = source.index('if shipping_source == "packlink" and shipping_gaps:')
    end = source.index('    calls_started = []', start)
    branch = source[start:end]

    assert 'hydrate_amazon_tracking_for_order(' not in branch
    assert 'hydrate_amazon_purchased_label_for_order(' not in branch
    assert 'if gaps & promise_gaps:' in branch
    assert 'refresh_exact_amazon_order(row)' in branch
    assert '"marketplace_write_started": False' in branch


def test_recover_missing_never_enumerates_beyond_selected_record():
    source = SOURCE.read_text(encoding="utf-8")

    assert "_candidate_order_ids" not in source
    assert "recover_packlink_shipments_for_day" not in source
    assert "find_shipment_by_custom_reference" not in source

    # The DB gate and execution both retain the browser-selected identity.
    assert "before = _database_readback(store_id, order_id)" in source
    assert "MarketplaceOrder.store_id == store_id" in source
    assert "MarketplaceOrder.marketplace_order_id == order_id" in source


def test_packlink_recovery_uses_only_selected_records_persisted_reference():
    source = SOURCE.read_text(encoding="utf-8")
    start = source.index('if shipping_source == "packlink" and shipping_gaps:')
    end = source.index('    calls_started = []', start)
    branch = source[start:end]

    assert 'provider_reference = str(shipment_truth.get("provider_shipment_id")' in branch
    assert "adapter.get_shipment(provider_reference)" in branch
    assert "adapter.get_tracking_status(reference=provider_reference)" in branch
    assert "find_shipment_by_custom_reference" not in branch
    assert "recover_packlink_shipments_for_day" not in branch


def test_committed_refresh_queues_exact_identities_without_dropping_events():
    source = Path("static/js/fbm_tracking_journey.js").read_text(encoding="utf-8")

    assert "const governedLiveRefreshQueue = new Map();" in source
    assert "governedLiveRefreshQueue.set(identity, detail);" in source
    assert "while (governedLiveRefreshQueue.size)" in source
    assert "await applyCommittedFbmSnapshot(detail);" in source
    assert "if (governedLiveRefreshPending) return;\n        const row = committedFbmRow(detail);" not in source
    assert "setInterval(" not in source


def test_targeted_refresh_never_reads_cross_order_price_memory():
    source = Path("services/governed_fbm_page_alignment.py").read_text(encoding="utf-8")

    assert "if missing_spend_rows and not targeted_refresh:" in source
    assert 'request.headers.get("X-BT38-UI-Refresh") == "targeted"' in source
    assert "MarketplaceOrder.marketplace_order_id == targeted_marketplace_order_id" in source
    assert "MarketplaceOrder.store_id == targeted_store_id" in source


def test_verified_manual_recovery_reuses_exact_committed_refresh_owner():
    source = Path("templates/fbm.html").read_text(encoding="utf-8")

    assert "recoveredRefreshScopes=new Map()" in source
    assert "recoveredRefreshScopes.set(`${storeId}:${orderId}`" in source
    assert "source:'manual_exact_recovery_verified'" in source
    assert "store_id:storeId,marketplace_order_id:orderId" in source
    assert "recoveredRefreshScopes.forEach(scope=>{" in source
    assert "window.bt38RefreshExactCommittedFbmRow(scope)" in source
    assert "window.location.reload()" not in source


def test_tracking_history_stays_aligned_when_exact_row_refreshes():
    source = Path("static/js/fbm_tracking_journey.js").read_text(encoding="utf-8")

    # Tracking History must never defer committed truth until its modal closes.
    assert "'#fbmShippingModal.show, #fbmTrackingJourneyModal.show'" not in source
    assert "const activeShippingModal = document.querySelector('#fbmShippingModal.show')" in source

    # The exact replacement row is the modal authority too. If Tracking History
    # is already open, re-render it immediately from the newly persisted row.
    assert "const replacementRow = document.importNode(freshRow, true)" in source
    assert "row.replaceWith(replacementRow)" in source
    assert "document.querySelector('#fbmTrackingJourneyModal.show')" in source
    assert "replacementRow.querySelector('.fbm-tracking-journey')" in source
    assert "openPersistedJourney(currentTrackingButton)" in source


def test_verified_recovery_calls_single_exact_refresh_owner_directly():
    template = Path("templates/fbm.html").read_text(encoding="utf-8")
    source = Path("static/js/fbm_tracking_journey.js").read_text(encoding="utf-8")

    assert "window.bt38RefreshExactCommittedFbmRow = function(detail)" in source
    assert "enqueueCommittedFbmRefresh(detail || {})" in source
    assert "typeof window.bt38RefreshExactCommittedFbmRow==='function'" in template
    assert "window.bt38RefreshExactCommittedFbmRow(scope)" in template
    assert "location.reload(" not in template
    assert "setInterval(" not in source


def test_open_tracking_modal_refresh_is_exact_identity_only():
    source = Path("static/js/fbm_tracking_journey.js").read_text(encoding="utf-8")

    assert "modalElement.dataset.storeId = String(identityRow.dataset.storeId || '')" in source
    assert "modalElement.dataset.marketplaceOrderId = String(identityRow.dataset.marketplaceOrderId || '')" in source
    assert "String(openTrackingModal.dataset.storeId || '') === storeId" in source
    assert "String(openTrackingModal.dataset.marketplaceOrderId || '') === marketplaceOrderId" in source


def test_full_page_and_targeted_refresh_share_one_canonical_row_renderer():
    full_page = Path("templates/fbm.html").read_text(encoding="utf-8")
    fragment = Path("templates/_fbm_history_rows.html").read_text(encoding="utf-8")
    canonical = Path("templates/_fbm_order_rows.html").read_text(encoding="utf-8")

    assert "{% include '_fbm_order_rows.html' %}" in full_page
    assert "{% include '_fbm_order_rows.html' %}" in fragment
    assert full_page.count('class="fbm-order-row"') == 0
    assert fragment.count('class="fbm-order-row"') == 0
    assert canonical.count('class="fbm-order-row"') == 1
    assert 'data-lifecycle-status="{{ lifecycle_status }}"' in canonical
    assert "persisted_delivered" in canonical


def test_exact_browser_row_replacement_uses_store_and_marketplace_order_identity():
    source = Path("static/js/fbm_tracking_journey.js").read_text(encoding="utf-8")

    assert 'data-marketplace-order-id="${CSS.escape(marketplaceOrderId)}"' in source
    assert 'data-store-id="${CSS.escape(storeId)}"' in source
    assert "const freshRowSelector =" in source
