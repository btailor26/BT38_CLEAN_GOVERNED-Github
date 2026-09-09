(function () {
    'use strict';

    const TRACKING_TRIGGER_SELECTOR = '.fbm-tracking-journey, .fbm-orders-table a[href*="ebay.co.uk/mesh/ord/details"], .fbm-orders-table a[href*="sellercentral.amazon.co.uk/orders-v3/order/"]';

    function esc(value) {
        return String(value ?? '').replace(/[&<>"']/g, function (char) {
            return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char];
        });
    }

    function displayDate(value) {
        if (!value) return '';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return '';
        return new Intl.DateTimeFormat('en-GB', {day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit'}).format(date);
    }

    function performanceHtml(row) {
        const performance = String(row?.dataset?.deliveryPerformance || '').trim().toLowerCase();
        if (performance === 'on_time') return '<span class="badge bg-success">On time</span>';
        if (performance === 'late') return '<span class="badge bg-danger">Late</span>';
        if (performance === 'timing_unavailable') return '<span class="badge bg-secondary">Delivered · timing unavailable</span>';
        return '';
    }

    function promiseHtml(row) {
        const shipBy = displayDate(row?.dataset?.shipByAt || '');
        const deliverBy = displayDate(row?.dataset?.deliveryPromiseAt || '');
        if (!shipBy && !deliverBy) return '<div class="text-muted small">Marketplace delivery promise unavailable in persisted BT38 DB.</div>';
        return `<div class="small text-muted mb-1">Marketplace promise · persisted BT38 DB</div>${shipBy ? `<div class="small"><strong>Ship by:</strong> ${esc(shipBy)}</div>` : ''}${deliverBy ? `<div class="small"><strong>Deliver by:</strong> ${esc(deliverBy)}</div>` : ''}`;
    }

    function milestoneHtml(row) {
        const journeyCell = row?.children?.[8] || null;
        const badges = journeyCell ? Array.from(journeyCell.querySelectorAll('.fbm-journey-steps .badge')) : [];
        return badges.map(function (badge) {
            const text = String(badge.textContent || '').trim();
            const confirmed = badge.classList.contains('bg-success') || badge.classList.contains('bg-primary');
            return `<div class="border-start border-3 ${confirmed ? 'border-success' : 'border-secondary'} ps-3 py-2 mb-2"><div class="d-flex justify-content-between gap-3"><div class="fw-semibold">${esc(text)}</div><span class="badge ${confirmed ? 'bg-success' : 'bg-light text-muted border'}">${confirmed ? 'Confirmed' : 'Pending'}</span></div></div>`;
        }).join('') || '<div class="alert alert-light border mb-0">No persisted carrier milestone is available yet.</div>';
    }

    function alignRowPerformance(row) {
        const journeyCell = row?.children?.[8] || null;
        if (!journeyCell) return;
        let holder = journeyCell.querySelector('.fbm-delivery-performance');
        if (!holder) {
            holder = document.createElement('div');
            holder.className = 'fbm-row-note fbm-delivery-performance mt-1';
            journeyCell.appendChild(holder);
        }
        holder.innerHTML = performanceHtml(row);
    }

    function openAlignedJourney(button) {
        const row = button.closest('.fbm-order-row');
        const modalElement = document.getElementById('fbmTrackingJourneyModal');
        const body = document.getElementById('fbmTrackingJourneyBody');
        const subtitle = document.getElementById('fbmTrackingJourneySubtitle');
        if (!row || !modalElement || !body) return;
        const tracking = button.dataset.trackingNumber || String(button.textContent || '').trim() || '—';
        const shipmentCell = row.children?.[7] || null;
        const carrier = String(shipmentCell?.querySelector('strong')?.textContent || 'Carrier').trim();
        const service = String(shipmentCell?.querySelector('.text-muted')?.textContent || '').trim();
        if (subtitle) subtitle.textContent = tracking;
        body.innerHTML = `<div class="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-3"><div><div class="fw-semibold">${esc(carrier)}${service ? ` · ${esc(service)}` : ''}</div><div class="small">Tracking: <code>${esc(tracking)}</code></div><div class="small text-muted">Journey source: persisted BT38 DB</div></div><div>${performanceHtml(row)}</div></div><div class="border rounded p-3 mb-3">${promiseHtml(row)}</div><div class="fw-semibold mb-2">Shipment journey</div>${milestoneHtml(row)}`;
        bootstrap.Modal.getOrCreateInstance(modalElement).show();
    }

    function intercept(event) {
        const button = event.target && event.target.closest ? event.target.closest(TRACKING_TRIGGER_SELECTOR) : null;
        if (!button) return;
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        openAlignedJourney(button);
    }

    function install() {
        if (document.documentElement.dataset.bt38PromiseJourneyAligned === '4') return;
        document.documentElement.dataset.bt38PromiseJourneyAligned = '4';
        document.querySelectorAll('.fbm-order-row').forEach(alignRowPerformance);
        window.addEventListener('click', intercept, true);
        window.addEventListener('keydown', function (event) {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            intercept(event);
        }, true);
        document.addEventListener('fbm:rows-updated', function () {
            document.querySelectorAll('.fbm-order-row').forEach(alignRowPerformance);
        });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install, {once: true});
    else install();
})();
