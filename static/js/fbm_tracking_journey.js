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

    // Single reporting path: persisted Tracking history is the source of truth.
    // Journey milestones come only from explicit persisted carrier events.
    // Never promote marketplace "shipped" to pickup or "delivered" backwards into transit.
    function milestoneTruthFromTrackingHistory(row) {
        let events = [];
        try { events = JSON.parse(row.dataset.trackingEvents || '[]'); } catch (_) { events = []; }
        if (!Array.isArray(events)) events = [];
        const norm = value => String(value || '').trim().toLowerCase().replace(/[ -]+/g, '_');
        const eventTime = event => event.event_time || event.eventTime || event.occurred_at || event.occurredAt || event.timestamp || null;
        const statusOf = event => norm(event.status || event.event_status || event.code);
        const pickup = events.find(event => ['carrier_accepted','accepted','picked_up','collected'].includes(statusOf(event)));
        const movement = events.find(event => ['in_transit','out_for_delivery'].includes(statusOf(event)));
        const outForDelivery = events.find(event => statusOf(event) === 'out_for_delivery');
        const delivered = events.find(event => statusOf(event) === 'delivered');
        return {
            carrierAcceptedAt: pickup ? eventTime(pickup) : '',
            firstMovementAt: movement ? eventTime(movement) : '',
            outForDeliveryAt: outForDelivery ? eventTime(outForDelivery) : '',
            deliveredAt: delivered ? eventTime(delivered) : ''
        };
    }

    function alignJourneyFromTrackingHistory() {
        document.querySelectorAll('.fbm-order-row').forEach(row => {
            if (!String(row.dataset.trackingEvents || '').trim()) return;
            const truth = milestoneTruthFromTrackingHistory(row);
            row.dataset.carrierAcceptedAt = truth.carrierAcceptedAt;
            row.dataset.firstMovementAt = truth.firstMovementAt;
            row.dataset.outForDeliveryAt = truth.outForDeliveryAt;
            row.dataset.deliveredAt = truth.deliveredAt;
            const badges = row.querySelectorAll('.fbm-journey-steps .badge');
            const values = [truth.carrierAcceptedAt, truth.firstMovementAt, truth.deliveredAt];
            badges.forEach((badge, index) => {
                badge.className = values[index] ? 'badge bg-success' : 'badge bg-light text-muted border';
            });
        });
    }

    function alignPersistedLifecycle() {
        document.querySelectorAll('.fbm-order-row').forEach(row => {
            const status = String(row.dataset.lifecycleStatus || '').trim().toLowerCase();
            const orderCell = row.children && row.children[2];
            if (status && orderCell && !orderCell.querySelector('.bt38-order-lifecycle')) {
                const wrap = document.createElement('div');
                wrap.className = 'small mt-1 bt38-order-lifecycle';
                const badge = document.createElement('span');
                badge.className = `badge ${lifecycleClass(status)}`;
                badge.textContent = lifecycleLabel(status);
                wrap.appendChild(badge);
                orderCell.appendChild(wrap);
            }
        });
    }

    let governedLiveRefreshPending = false;

    async function applyCommittedFbmSnapshot() {
        if (governedLiveRefreshPending) return;
        governedLiveRefreshPending = true;
        try {
            const response = await fetch(window.location.href, {method:'GET', credentials:'same-origin', cache:'no-store', headers: {'Accept': 'text/html'}});
            if (!response.ok) throw new Error(`FBM refresh failed (HTTP ${response.status})`);
            const html = await response.text();
            const parsed = new DOMParser().parseFromString(html, 'text/html');
            const dataNode = parsed.getElementById('bt38FbmLifecycleTabsData');
            const countsNode = parsed.getElementById('bt38FbmLifecycleCountsData');
            if (!dataNode || !countsNode || typeof window.BT38FBMApplyCommittedSnapshot !== 'function') return;
            const nextData = JSON.parse(dataNode.textContent || '{}');
            const nextCounts = JSON.parse(countsNode.textContent || '{}');
            document.querySelectorAll('.fbm-order-row').forEach(row => {
                const freshRow = parsed.querySelector(`.fbm-order-row[data-order-id="${CSS.escape(String(row.dataset.orderId || ''))}"]`);
                if (!freshRow) return;
                // Keep the visible row on the exact same persisted DB truth as
                // the tracking popup. The fresh /fbm snapshot already carries
                // these governed data attributes; copy them before the committed
                // snapshot event lets the canonical journey owner recolour.
                [
                    'lifecycleStatus',
                    'shipmentState',
                    'carrierAcceptedAt',
                    'firstMovementAt',
                    'deliveredAt',
                    'deliveryPerformance',
                    'trackingEvents',
                    'lastProviderCheckedAt',
                    'lastProviderStatus',
                    'shipByAt',
                    'earliestDeliveryAt',
                    'deliveryPromiseAt',
                    'shippingSource',
                    'carrier',
                    'service',
                    'trackingNumber',
                    'providerShipmentId',
                    'shippingCost',
                    'shippingCostCurrency',
                    'shippingCostRecords'
                ].forEach(key => {
                    row.dataset[key] = freshRow.dataset[key] || '';
                });
                row.dataset.labelReady = freshRow.dataset.labelReady || '0';
            });
            window.BT38FBMApplyCommittedSnapshot(nextData, nextCounts);
            alignJourneyFromTrackingHistory();
            alignPersistedLifecycle();
            updateSelectedPacklinkLabelAction();
        } catch (error) {
            console.warn('[BT38 FBM] committed session refresh unavailable', error);
        } finally {
            governedLiveRefreshPending = false;
        }
    }

    function refreshFbmFromGovernedEvent() {
        const activeModal = document.querySelector('#fbmShippingModal.show, #fbmTrackingJourneyModal.show');
        if (activeModal) {
            activeModal.addEventListener('hidden.bs.modal', () => void applyCommittedFbmSnapshot(), {once:true});
            return;
        }
        void applyCommittedFbmSnapshot();
    }

    window.addEventListener('bt38-marketplace-event', refreshFbmFromGovernedEvent);

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

    // Retired child alignment loaders. Their active behavior is owned by the
    // canonical FBM page assets/injected authorities; this bootstrap must not
    // load duplicate eBay, legacy journey, or delivery-promise scripts.

    function startSelectedPacklinkLabelAction() {
        installSelectedPacklinkLabelAction();
        updateSelectedPacklinkLabelAction();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            alignJourneyFromTrackingHistory();
            alignPersistedLifecycle();
            startSelectedPacklinkLabelAction();
        }, {once:true});
    } else {
        alignJourneyFromTrackingHistory();
        alignPersistedLifecycle();
        startSelectedPacklinkLabelAction();
    }

    // Retired: no dynamic child-script bootstrap from this canonical entry.
})(document);