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
                const orderId = String(row.dataset.orderId || '');
                const freshRow = parsed.querySelector(`.fbm-order-row[data-order-id="${CSS.escape(orderId)}"]`);
                if (!freshRow) return;
                // The server-rendered row is the committed DB presentation
                // authority. Replace the exact row rather than copying only
                // datasets, otherwise visible tracking/journey/cost/source can
                // remain stale while hidden data is already current.
                row.replaceWith(document.importNode(freshRow, true));
            });
            // Rebuild the existing FBM browser-session owner from the replaced
            // rows; no second refresh owner, timer, poller or marketplace read.
            window.BT38FBMApplyCommittedSnapshot(nextData, nextCounts);
            document.dispatchEvent(new CustomEvent('bt38-fbm-working-set-expanded', {
                detail: {reason: 'committed_event_refresh'}
            }));
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

    function escapeJourney(value) {
        return String(value == null ? '' : value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
    }

    function journeyDate(value) {
        if (!value) return 'Time unavailable';
        const parsed = new Date(value);
        return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString('en-GB', {day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'});
    }

    function persistedTrackingEvents(row) {
        try {
            const value = JSON.parse(row.dataset.trackingEvents || '[]');
            return Array.isArray(value) ? value : [];
        } catch (_error) {
            return [];
        }
    }

    function openPersistedJourney(button) {
        const row = button.closest('.fbm-order-row');
        const modalElement = document.getElementById('fbmTrackingJourneyModal');
        const body = document.getElementById('fbmTrackingJourneyBody');
        const subtitle = document.getElementById('fbmTrackingJourneySubtitle');
        if (!row || !modalElement || !body) return;

        const tracking = row.dataset.trackingNumber || button.dataset.trackingNumber || String(button.textContent || '').trim();
        const carrier = row.dataset.carrier || '—';
        const service = row.dataset.service || '';
        const events = persistedTrackingEvents(row);
        const accepted = row.dataset.carrierAcceptedAt || '';
        const moved = row.dataset.firstMovementAt || '';
        const delivered = row.dataset.deliveredAt || '';
        const performance = String(row.dataset.deliveryPerformance || '').toLowerCase();
        const latestPromise = row.dataset.deliveryPromiseAt || '';

        const state = delivered ? 'Delivered' : moved ? 'In transit' : accepted ? 'Picked up' : 'Waiting for carrier update';
        const journey = [
            ['Picked up', Boolean(accepted || moved || delivered)],
            ['In transit', Boolean(moved || delivered)],
            ['Delivered', Boolean(delivered)]
        ].map(([label, active]) => '<span class="badge '+(active ? 'bg-success' : 'bg-light text-muted border')+' me-1">'+label+'</span>').join('');

        const promise = latestPromise
            ? '<div class="border rounded p-3 mb-3"><div class="small text-muted">Marketplace delivery promise</div><div>'+escapeJourney(journeyDate(latestPromise))+(performance === 'late' ? ' <span class="badge bg-danger">Late</span>' : '')+'</div></div>'
            : '<div class="alert alert-light border">Marketplace delivery promise unavailable in persisted BT38 DB.</div>';

        const history = events.length ? events.map(event => {
            const title = event.description || event.status || 'Carrier update';
            const detail = event.detail && event.detail !== title ? '<div class="small text-muted">'+escapeJourney(event.detail)+'</div>' : '';
            const location = event.location ? '<div class="small text-muted">'+escapeJourney(event.location)+'</div>' : '';
            return '<div class="border-start border-3 ps-3 py-2 mb-2"><div class="fw-semibold">'+escapeJourney(title)+'</div>'+detail+location+'<div class="small text-muted">'+escapeJourney(journeyDate(event.event_time || event.observed_at))+'</div></div>';
        }).join('') : '<div class="text-muted">No detailed carrier scan history has been persisted yet.</div>';

        if (subtitle) subtitle.textContent = tracking || 'Tracking history';
        body.innerHTML =
            '<div class="fw-semibold">'+escapeJourney(carrier)+(service ? ' · '+escapeJourney(service) : '')+'</div>'+
            '<div class="small mb-1">Tracking: <code>'+escapeJourney(tracking || '—')+'</code></div>'+
            '<div class="small text-muted mb-3">Tracking authority: Persisted shipment · persisted BT38 DB</div>'+
            promise+
            '<div class="fw-semibold mb-2">Shipment journey</div>'+
            '<div class="mb-2">'+journey+'</div>'+
            '<div class="fw-semibold mb-3">'+escapeJourney(state)+'</div>'+
            (!accepted && !moved && !delivered ? '<div class="text-muted mb-3">No carrier tracking movement has been received yet.</div>' : '')+
            '<div class="fw-semibold mb-2">Tracking history</div>'+
            history;
        bootstrap.Modal.getOrCreateInstance(modalElement).show();
    }

    document.addEventListener('click', event => {
        const button = event.target && event.target.closest ? event.target.closest('.fbm-tracking-journey') : null;
        if (!button) return;
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        openPersistedJourney(button);
    }, true);

    // Retired child alignment loaders. Their active behavior is owned by the
    // canonical FBM page assets/injected authorities; this bootstrap must not
    // load duplicate eBay, legacy journey, or delivery-promise scripts.

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

    // Retired: no dynamic child-script bootstrap from this canonical entry.
})(document);