(function () {
    'use strict';

    function esc(value) {
        return String(value ?? '').replace(/[&<>"']/g, function (char) {
            return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char];
        });
    }

    function parseDate(value) {
        if (!value) return null;
        const parsed = new Date(value);
        return Number.isNaN(parsed.getTime()) ? null : parsed;
    }

    function formatDate(value) {
        const parsed = parseDate(value);
        if (!parsed) return '—';
        return parsed.toLocaleString('en-GB', {
            day: '2-digit', month: 'short', year: 'numeric',
            hour: '2-digit', minute: '2-digit'
        });
    }

    function labelStatus(value) {
        const status = String(value || '').trim().toLowerCase();
        const labels = {
            in_transit: 'In transit',
            out_for_delivery: 'Out for delivery',
            delivered: 'Delivered',
            accepted: 'Picked up',
            carrier_accepted: 'Picked up',
            collected: 'Picked up',
            picked_up: 'Picked up',
            shipped: 'Dispatched'
        };
        return labels[status] || String(value || '').replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase());
    }

    function currentStatus(row) {
        return row.dataset.lastProviderStatus || row.dataset.shipmentState || row.dataset.lifecycleStatus || '';
    }

    function eventRows(row) {
        const events = [];
        function add(time, title, detail) {
            if (!time) return;
            events.push({time: time, title: title, detail: detail || ''});
        }

        add(row.dataset.marketplaceCreatedAt || row.dataset.orderCreatedAt, 'Order received', 'Marketplace order persisted in BT38');
        add(row.dataset.labelPurchasedAt, 'Label purchased', row.dataset.shippingSource ? `${row.dataset.shippingSource} postage purchased` : 'Postage purchased');
        add(row.dataset.marketplaceConfirmedAt, 'Marketplace dispatch confirmed', 'Tracking / dispatch confirmation persisted');
        add(row.dataset.carrierAcceptedAt, 'Picked up', row.dataset.carrier ? `${row.dataset.carrier} accepted the parcel` : 'Carrier accepted the parcel');
        add(row.dataset.firstMovementAt, 'Movement detected', row.dataset.carrier ? `${row.dataset.carrier} first carrier movement persisted` : 'First carrier movement persisted');

        const providerChecked = row.dataset.lastProviderCheckedAt;
        const providerStatus = row.dataset.lastProviderStatus;
        if (providerChecked && providerStatus) {
            add(providerChecked, labelStatus(providerStatus), `Latest persisted ${row.dataset.shippingSource || 'carrier'} status`);
        }

        add(row.dataset.deliveredAt, 'Delivered', 'Delivery completion persisted');
        events.sort(function (a, b) {
            return (parseDate(a.time)?.getTime() || 0) - (parseDate(b.time)?.getTime() || 0);
        });
        return events;
    }

    function promiseHtml(row) {
        const shipBy = row.dataset.shipByAt;
        const earliest = row.dataset.earliestDeliveryAt;
        const latest = row.dataset.deliveryPromiseAt;
        if (!shipBy && !earliest && !latest) return '';
        return `<div class="border rounded p-3 mb-3"><div class="fw-semibold mb-1">Delivery commitment</div>` +
            `<div class="small text-muted">Ship by: ${esc(formatDate(shipBy))}</div>` +
            `<div class="small text-muted">Delivery: ${esc(formatDate(earliest))} → ${esc(formatDate(latest))}</div></div>`;
    }

    function movementHtml(row, trigger) {
        const carrier = row.dataset.carrier || trigger.dataset.carrier || 'Carrier';
        const service = row.dataset.service || '';
        const source = row.dataset.shippingSource || 'Persisted BT38 shipment';
        const tracking = row.dataset.trackingNumber || trigger.dataset.trackingNumber || String(trigger.textContent || '').trim() || '—';
        const providerReference = row.dataset.providerShipmentId || '';
        const status = labelStatus(currentStatus(row));
        const events = eventRows(row);
        const bodyRows = events.length ? events.map(function (event) {
            return `<tr><td class="text-nowrap text-muted">${esc(formatDate(event.time))}</td><td><strong>${esc(event.title)}</strong><div class="small text-muted">${esc(event.detail)}</div></td></tr>`;
        }).join('') : '<tr><td colspan="2" class="text-muted">No persisted movement milestones are available yet.</td></tr>';

        return `<div class="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-3">` +
            `<div><div class="fw-semibold">${esc(carrier)}${service ? ` · ${esc(service)}` : ''}</div>` +
            `<div class="small">Tracking: <code>${esc(tracking)}</code></div>` +
            `${providerReference ? `<div class="small text-muted">Shipment: ${esc(providerReference)}</div>` : ''}` +
            `<div class="small text-muted">Journey source: ${esc(source)} / persisted BT38 state</div></div>` +
            `${status ? `<span class="badge bg-success">${esc(status)}</span>` : ''}</div>` +
            promiseHtml(row) +
            `<div class="fw-semibold mb-2">Shipment movement</div>` +
            `<div class="table-responsive"><table class="table table-sm align-middle mb-0"><thead class="table-light"><tr><th>Time</th><th>Movement</th></tr></thead><tbody>${bodyRows}</tbody></table></div>`;
    }

    function openPersistedJourney(trigger) {
        const row = trigger.closest('.fbm-order-row');
        if (!row) return false;
        const modalElement = document.getElementById('fbmTrackingJourneyModal');
        const body = document.getElementById('fbmTrackingJourneyBody');
        const subtitle = document.getElementById('fbmTrackingJourneySubtitle');
        if (!modalElement || !body || !window.bootstrap || !bootstrap.Modal) return false;
        const tracking = row.dataset.trackingNumber || trigger.dataset.trackingNumber || String(trigger.textContent || '').trim();
        if (subtitle) subtitle.textContent = tracking || 'Tracking journey';
        body.innerHTML = movementHtml(row, trigger);
        bootstrap.Modal.getOrCreateInstance(modalElement).show();
        return true;
    }

    document.addEventListener('click', function (event) {
        const trigger = event.target.closest('.fbm-tracking-journey');
        if (!trigger) return;
        if (!openPersistedJourney(trigger)) return;
        event.preventDefault();
        event.stopImmediatePropagation();
    }, true);

    document.addEventListener('keydown', function (event) {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        const trigger = event.target.closest('.fbm-tracking-journey');
        if (!trigger) return;
        if (!openPersistedJourney(trigger)) return;
        event.preventDefault();
        event.stopImmediatePropagation();
    }, true);
})();
