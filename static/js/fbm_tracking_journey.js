/* BT38 FBM asset alignment bootstrap.
 * Load native eBay shipping before the preserved tracking journey so the
 * capture-phase native handler owns eBay Shipping and the legacy Seller Hub
 * handler cannot run first.
 *
 * Journey colour rule:
 * - persisted label/postage created without carrier acceptance => Picked up neutral
 * - persisted carrier pickup/acceptance => Picked up GREEN
 * - persisted carrier movement => In transit GREEN
 * - delivery timing colour remains owned by the delivery-promise journey
 *
 * Asset rule:
 * - every dynamically loaded FBM journey asset carries the deployed entry
 *   asset version; when an older unversioned page is still open, a per-load
 *   revision prevents stale child scripts surviving a browser refresh.
 */
(function (document) {
    'use strict';

    const bootstrapScript = document.currentScript;
    const bootstrapUrl = bootstrapScript && bootstrapScript.src
        ? new URL(bootstrapScript.src, window.location.href)
        : null;
    const assetRevision = bootstrapUrl && bootstrapUrl.searchParams.get('v')
        ? bootstrapUrl.searchParams.get('v')
        : String(Date.now());

    function assetUrl(path) {
        const separator = String(path || '').includes('?') ? '&' : '?';
        return `${path}${separator}v=${encodeURIComponent(assetRevision)}`;
    }

    function lifecycleLabel(status) {
        const labels = {
            pending: 'Pending', unshipped: 'Confirmed', order: 'Confirmed', confirmed: 'Confirmed',
            partially_shipped: 'Partially dispatched', shipped: 'Dispatched', accepted: 'Picked up',
            carrier_accepted: 'Picked up', collected: 'Picked up', picked_up: 'Picked up',
            in_transit: 'In transit', out_for_delivery: 'Out for delivery', delivered: 'Delivered',
            return_requested: 'Return requested', returned: 'Returned', refund_requested: 'Refund requested',
            refunded: 'Refunded', replacement_requested: 'Replacement requested', replacement: 'Replacement',
            case_open: 'Issue / case', dispute: 'Dispute', chargeback: 'Chargeback',
            cancel_requested: 'Cancellation requested', cancelled: 'Cancelled'
        };
        return labels[status] || String(status || '').replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase());
    }

    function lifecycleClass(status) {
        if (['delivered', 'picked_up', 'accepted', 'carrier_accepted', 'collected', 'in_transit', 'out_for_delivery'].includes(status)) return 'bg-success';
        if (['return_requested', 'returned', 'refund_requested', 'refunded', 'case_open', 'dispute', 'chargeback', 'cancel_requested', 'cancelled'].includes(status)) return 'bg-danger';
        if (['replacement_requested', 'replacement'].includes(status)) return 'bg-info text-dark';
        if (status === 'pending') return 'bg-warning text-dark';
        if (['shipped', 'partially_shipped'].includes(status)) return 'bg-primary';
        return 'bg-light text-dark border';
    }

    function labelOrTrackingStageReached(row) {
        return String(row && row.dataset ? row.dataset.labelReady || '' : '') === '1';
    }

    // Journey stage colours are owned by
    // fbm_delivery_promise_journey_alignment.js from persisted milestone truth.
    // This bootstrap must not independently repaint those badges.
    function alignPersistedLifecycle() {}

    document.addEventListener('bt38-fbm-committed-snapshot-applied', function () {
        updateSelectedPacklinkLabelAction();
    });

    function selectedPacklinkRows() {
        const selected = [];
        const seen = new Set();
        document.querySelectorAll('.fbm-order-checkbox:checked').forEach(checkbox => {
            const row = checkbox.closest('.fbm-order-row');
            const statusButton = row && row.querySelector('.packlink-existing-status[data-shipment-id]');
            const shipmentId = statusButton && String(statusButton.dataset.shipmentId || '').trim();
            if (!row || !shipmentId || seen.has(shipmentId)) return;
            seen.add(shipmentId);
            selected.push({row, shipmentId});
        });
        return selected;
    }

    function updateSelectedPacklinkLabelAction() {
        const button = document.getElementById('dispatchedPacklinkLabelAction');
        if (!button) return;
        const selected = selectedPacklinkRows();
        if (selected.length !== 1) {
            button.disabled = true;
            button.hidden = selected.length === 0;
            button.textContent = 'Download Label';
            return;
        }
        const row = selected[0].row;
        const hasLabel = String(row.dataset.labelReady || '') === '1';
        button.hidden = false;
        button.disabled = false;
        button.textContent = hasLabel ? 'Reprint Label' : 'Download Label';
    }

    async function runSelectedPacklinkLabelAction(button) {
        const selected = selectedPacklinkRows();
        if (selected.length !== 1) return;
        const item = selected[0];
        const bridge = window.BT38FBMQZ;
        const status = document.getElementById('qzStatus');
        button.disabled = true;
        try {
            if (!bridge || typeof bridge.packlinkStatus !== 'function') throw new Error('Packlink label bridge is unavailable.');
            const payload = await bridge.packlinkStatus(item.shipmentId);
            const label = payload.label || null;
            if (!payload.label_ready || !label || !(label.url || label.base64 || label.data)) {
                item.row.dataset.labelReady = '0';
                button.textContent = 'Download Label';
                if (status) {
                    status.className = 'small text-warning mt-2';
                    status.textContent = payload.message || 'No Packlink label is available to download for this paid shipment yet.';
                }
                return;
            }

            item.row.dataset.labelReady = '1';
            button.textContent = 'Reprint Label';
            try {
                const printed = await bridge.printLabel(label);
                if (status) {
                    status.className = 'small text-success mt-2';
                    status.textContent = `Packlink label downloaded and sent to ${printed.printer}`;
                }
            } catch (printError) {
                console.warn('[BT38 FBM] Packlink label recovered; QZ print unavailable', printError);
                if (label.url) {
                    window.open(label.url, '_blank', 'noopener');
                } else if (label.base64) {
                    const binary = window.atob(String(label.base64));
                    const bytes = new Uint8Array(binary.length);
                    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
                    const format = String(label.format || 'pdf').toLowerCase();
                    const blobUrl = URL.createObjectURL(new Blob([bytes], {type:format === 'pdf' ? 'application/pdf' : 'application/octet-stream'}));
                    const anchor = document.createElement('a');
                    anchor.href = blobUrl;
                    anchor.download = `BT38-Packlink-label.${format}`;
                    anchor.click();
                    window.setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
                }
                if (status) {
                    status.className = 'small text-warning mt-2';
                    status.textContent = 'Packlink label downloaded; QZ printing was unavailable, so the label was opened for manual print.';
                }
            }
        } catch (error) {
            if (status) {
                status.className = 'small text-danger mt-2';
                status.textContent = error.message || 'Packlink label download failed.';
            }
        } finally {
            button.disabled = false;
            updateSelectedPacklinkLabelAction();
            alignPersistedLifecycle();
        }
    }

    function installSelectedPacklinkLabelAction() {
        if (document.getElementById('dispatchedPacklinkLabelAction')) return;
        const readyButton = document.getElementById('readyToShipSelected');
        if (!readyButton || !readyButton.parentNode) return;
        const button = document.createElement('button');
        button.id = 'dispatchedPacklinkLabelAction';
        button.type = 'button';
        button.className = 'btn btn-sm btn-outline-success';
        button.textContent = 'Download Label';
        button.hidden = true;
        button.disabled = true;
        readyButton.parentNode.insertBefore(button, readyButton.nextSibling);
        button.addEventListener('click', event => {
            event.preventDefault();
            event.stopPropagation();
            void runSelectedPacklinkLabelAction(button);
        });
        document.addEventListener('change', event => {
            if (event.target && (event.target.matches('.fbm-order-checkbox') || event.target.matches('#selectAllOrders'))) {
                window.setTimeout(updateSelectedPacklinkLabelAction, 0);
            }
        });
        updateSelectedPacklinkLabelAction();
    }

    async function handleExistingPacklinkLabel(event) {
        const button = event.target && event.target.closest ? event.target.closest('.packlink-existing-status[data-shipment-id]') : null;
        if (!button) return;
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        const bridge = window.BT38FBMQZ;
        const status = document.getElementById('qzStatus');
        const autoPrint = document.getElementById('qzAutoPrint');
        const row = button.closest('.fbm-order-row');
        button.disabled = true;
        try {
            if (!bridge || typeof bridge.packlinkStatus !== 'function') throw new Error('Packlink label bridge is unavailable.');
            const payload = await bridge.packlinkStatus(button.dataset.shipmentId);
            const label = payload.label || null;
            if (!payload.label_ready || !label || !(label.url || label.base64 || label.data)) {
                if (status) {
                    status.className = 'small text-warning mt-2';
                    status.textContent = payload.message || 'Packlink label is not ready yet.';
                }
                return;
            }
            if (row) row.dataset.labelReady = '1';
            updateSelectedPacklinkLabelAction();
            if (autoPrint && autoPrint.checked) {
                try {
                    const printed = await bridge.printLabel(label);
                    if (status) {
                        status.className = 'small text-success mt-2';
                        status.textContent = `Packlink label sent to ${printed.printer}`;
                    }
                    return;
                } catch (printError) {
                    console.warn('[BT38 FBM] Packlink label saved; QZ print unavailable', printError);
                }
            }
            if (label.url) {
                window.open(label.url, '_blank', 'noopener');
            } else if (label.base64) {
                const binary = window.atob(String(label.base64));
                const bytes = new Uint8Array(binary.length);
                for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
                const format = String(label.format || 'pdf').toLowerCase();
                const blobUrl = URL.createObjectURL(new Blob([bytes], {type:format === 'pdf' ? 'application/pdf' : 'application/octet-stream'}));
                const anchor = document.createElement('a');
                anchor.href = blobUrl;
                anchor.download = `BT38-Packlink-label.${format}`;
                anchor.click();
                window.setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
            }
            if (status) {
                status.className = 'small text-warning mt-2';
                status.textContent = 'Packlink label is ready; QZ auto-print was unavailable, so the saved label was opened for download.';
            }
        } catch (error) {
            if (status) {
                status.className = 'small text-danger mt-2';
                status.textContent = error.message || 'Packlink label check failed.';
            }
        } finally {
            button.disabled = false;
            alignPersistedLifecycle();
        }
    }

    document.addEventListener('click', event => { void handleExistingPacklinkLabel(event); }, true);

    function loadDeliveryPromiseAlignment() {
        if (document.querySelector('script[data-bt38-fbm-delivery-promise-alignment="1"]')) return;
        const alignment = document.createElement('script');
        alignment.src = assetUrl('/static/js/fbm_delivery_promise_journey_alignment.js');
        alignment.dataset.bt38FbmDeliveryPromiseAlignment = '1';
        document.head.appendChild(alignment);
    }

    function loadLegacy() {
        if (document.querySelector('script[data-bt38-fbm-tracking-legacy="1"]')) {
            alignPersistedLifecycle();
            loadDeliveryPromiseAlignment();
            return;
        }
        const legacy = document.createElement('script');
        legacy.src = assetUrl('/static/js/fbm_tracking_journey_legacy.js');
        legacy.dataset.bt38FbmTrackingLegacy = '1';
        legacy.onload = function () { alignPersistedLifecycle(); loadDeliveryPromiseAlignment(); };
        legacy.onerror = function () { alignPersistedLifecycle(); loadDeliveryPromiseAlignment(); };
        document.head.appendChild(legacy);
    }

    function startSelectedPacklinkLabelAction() {
        installSelectedPacklinkLabelAction();
        updateSelectedPacklinkLabelAction();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            alignPersistedLifecycle();
            startSelectedPacklinkLabelAction();
        }, {once:true});
    } else {
        alignPersistedLifecycle();
        startSelectedPacklinkLabelAction();
    }

    if (document.querySelector('script[data-bt38-ebay-native-bootstrap="1"]')) {
        loadLegacy();
        return;
    }
    const nativeScript = document.createElement('script');
    nativeScript.src = assetUrl('/static/js/fbm_ebay_shipping_alignment.js');
    nativeScript.dataset.bt38EbayNativeBootstrap = '1';
    nativeScript.onload = loadLegacy;
    nativeScript.onerror = loadLegacy;
    document.head.appendChild(nativeScript);
})(document);