(function () {
    'use strict';

    const TRACKING_TRIGGER_SELECTOR = '.fbm-tracking-journey, .fbm-orders-table a[href*="ebay.co.uk/mesh/ord/details"], .fbm-orders-table a[href*="sellercentral.amazon.co.uk/orders-v3/order/"]';

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

    function promiseFromRow(row) {
        const lines = row ? Array.from(row.querySelectorAll('.fbm-promise-line')) : [];
        let shipBy = '';
        let deliverBy = '';
        lines.forEach(function (line) {
            const text = String(line.textContent || '').replace(/\s+/g, ' ').trim();
            if (/^ship by\b/i.test(text)) shipBy = text.replace(/^ship by\s*/i, '').trim();
            if (/^deliver by\b/i.test(text)) deliverBy = text.replace(/^deliver by\s*/i, '').trim();
        });
        if (/^pending$/i.test(shipBy)) shipBy = '';
        if (/^pending$/i.test(deliverBy)) deliverBy = '';
        return {shipBy: row?.dataset?.shipByAt || shipBy, deliverBy: row?.dataset?.deliveryPromiseAt || deliverBy, shipByDisplay: shipBy, deliverByDisplay: deliverBy};
    }

    function promiseDate(promise) {
        const iso = parseDate(promise.deliverBy);
        if (iso) return iso;
        const text = String(promise.deliverBy || '').replace(/\s+/g, ' ').trim();
        const match = text.match(/(\d{1,2})\s+([A-Za-z]{3,9})(?:\s+(\d{4}))?(?:\s+(\d{1,2}):(\d{2}))?/i);
        if (!match) return null;
        const months = {jan:0,january:0,feb:1,february:1,mar:2,march:2,apr:3,april:3,may:4,jun:5,june:5,jul:6,july:6,aug:7,august:7,sep:8,sept:8,september:8,oct:9,october:9,nov:10,november:10,dec:11,december:11};
        const month = months[String(match[2]).toLowerCase()];
        if (month === undefined) return null;
        const year = match[3] ? Number(match[3]) : new Date().getFullYear();
        const hasTime = match[4] !== undefined;
        const result = new Date(year, month, Number(match[1]), hasTime ? Number(match[4]) : 23, hasTime ? Number(match[5]) : 59, hasTime ? 0 : 59, hasTime ? 0 : 999);
        return Number.isNaN(result.getTime()) ? null : result;
    }

    function persistedState(row) {
        const explicit = String(row?.dataset?.shipmentState || row?.dataset?.lifecycleStatus || '').trim().toLowerCase();
        if (explicit) return explicit;
        const journeyCell = row?.children?.[8] || null;
        if (!journeyCell) return '';
        const confirmed = Array.from(journeyCell.querySelectorAll('.fbm-journey-steps .badge')).filter(function (badge) { return badge.classList.contains('bg-success') || badge.classList.contains('bg-primary'); }).map(function (badge) { return String(badge.textContent || '').trim().toLowerCase(); });
        if (confirmed.some(function (value) { return value.includes('delivered'); })) return 'delivered';
        if (confirmed.some(function (value) { return value.includes('in transit'); })) return 'in_transit';
        if (confirmed.some(function (value) { return value.includes('picked up'); })) return 'accepted';
        return '';
    }

    function performanceHtml(row) {
        const promisedAt = promiseDate(promiseFromRow(row));
        if (!promisedAt) return '<span class="badge bg-secondary">Promise timing unavailable</span>';
        const state = persistedState(row);
        const deliveredAt = parseDate(row?.dataset?.deliveredAt || '');
        if (state === 'delivered') {
            if (!deliveredAt) return '<span class="badge bg-secondary">Delivered · timing unavailable</span>';
            return deliveredAt.getTime() <= promisedAt.getTime() ? '<span class="badge bg-success">On time</span>' : '<span class="badge bg-danger">Late</span>';
        }
        return Date.now() > promisedAt.getTime() ? '<span class="badge bg-danger">Late</span>' : '<span class="badge bg-success">On track</span>';
    }

    function promiseHtml(row) {
        const promise = promiseFromRow(row);
        if (!promise.shipBy && !promise.deliverBy) return '<div class="text-muted small">Marketplace delivery promise unavailable in persisted FBM projection.</div>';
        const ship = promise.shipByDisplay || promise.shipBy;
        const deliver = promise.deliverByDisplay || promise.deliverBy;
        return `<div class="small text-muted mb-1">Marketplace promise · persisted BT38 DB</div>${ship ? `<div class="small"><strong>Ship by:</strong> ${esc(ship)}</div>` : ''}${deliver ? `<div class="small"><strong>Deliver by:</strong> ${esc(deliver)}</div>` : ''}`;
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
        if (!holder) { holder = document.createElement('div'); holder.className = 'fbm-row-note fbm-delivery-performance mt-1'; journeyCell.appendChild(holder); }
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
        const carrier = button.dataset.carrier || String(shipmentCell?.querySelector('strong')?.textContent || 'Carrier').trim();
        const service = String(shipmentCell?.querySelector('.text-muted')?.textContent || '').trim();
        if (subtitle) subtitle.textContent = tracking;
        body.innerHTML = `<div class="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-3"><div><div class="fw-semibold">${esc(carrier)}${service ? ` · ${esc(service)}` : ''}</div><div class="small">Tracking: <code>${esc(tracking)}</code></div><div class="small text-muted">Journey source: persisted BT38 DB</div></div><div>${performanceHtml(row)}</div></div><div class="border rounded p-3 mb-3">${promiseHtml(row)}</div><div class="fw-semibold mb-2">Shipment journey</div>${milestoneHtml(row)}`;
        bootstrap.Modal.getOrCreateInstance(modalElement).show();
    }

    function intercept(event) {
        const button = event.target && event.target.closest ? event.target.closest(TRACKING_TRIGGER_SELECTOR) : null;
        if (!button) return;
        event.preventDefault(); event.stopPropagation(); event.stopImmediatePropagation();
        openAlignedJourney(button);
    }

    function install() {
        if (document.documentElement.dataset.bt38PromiseJourneyAligned === '3') return;
        document.documentElement.dataset.bt38PromiseJourneyAligned = '3';
        document.querySelectorAll('.fbm-order-row').forEach(alignRowPerformance);
        // Window capture runs before the preserved legacy document-capture handler.
        // Tracking clicks are presentation-only and can never reach a provider read.
        window.addEventListener('click', intercept, true);
        window.addEventListener('keydown', function (event) {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            intercept(event);
        }, true);
        document.addEventListener('fbm:rows-updated', function () { document.querySelectorAll('.fbm-order-row').forEach(alignRowPerformance); });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install, {once: true});
    else install();
})();