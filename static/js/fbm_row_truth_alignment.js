/* Presentation-only FBM row truth alignment.
 * Uses only data already rendered into the row. No fetch, DB read, provider call,
 * polling, timer or marketplace action is allowed here.
 */
(function (document) {
    'use strict';

    const pickupStates = new Set(['accepted', 'carrier_accepted', 'collected', 'picked_up']);
    const movementStates = new Set(['in_transit', 'out_for_delivery']);
    const dispatchedStates = new Set([
        'shipped', 'partially_shipped', 'partiallyshipped',
        'accepted', 'carrier_accepted', 'collected', 'picked_up',
        'in_transit', 'out_for_delivery', 'delivered'
    ]);

    function setBadge(badge, confirmed) {
        if (!badge) return;
        badge.classList.remove('bg-success', 'bg-danger', 'bg-primary', 'bg-warning', 'bg-info', 'bg-light', 'text-muted', 'text-dark', 'border');
        if (confirmed) {
            badge.classList.add('bg-success');
        } else {
            badge.classList.add('bg-light', 'text-muted', 'border');
        }
    }

    function alignJourney(row, status) {
        const journeyCell = row.children && row.children[8];
        if (!journeyCell) return;
        const badges = Array.from(journeyCell.querySelectorAll('.fbm-journey-steps .badge'));
        const pickedUp = badges.find(badge => /picked up/i.test(String(badge.textContent || '')));
        const inTransit = badges.find(badge => /in transit/i.test(String(badge.textContent || '')));
        const delivered = badges.find(badge => /delivered/i.test(String(badge.textContent || '')));

        // Always reset first so stale server/browser colour cannot survive a
        // newer persisted marketplace lifecycle snapshot.
        setBadge(pickedUp, false);
        setBadge(inTransit, false);
        setBadge(delivered, false);

        const pickupConfirmed = pickupStates.has(status) || movementStates.has(status) || status === 'delivered';
        const movementConfirmed = movementStates.has(status) || status === 'delivered';
        setBadge(pickedUp, pickupConfirmed);
        setBadge(inTransit, movementConfirmed);
        setBadge(delivered, status === 'delivered');

        if (pickedUp) pickedUp.title = pickupConfirmed ? 'Pickup confirmed by persisted marketplace lifecycle' : 'Pickup not confirmed';
        if (inTransit) inTransit.title = movementConfirmed ? 'Movement confirmed by persisted marketplace lifecycle' : 'Movement not confirmed';
        if (delivered) delivered.title = status === 'delivered' ? 'Delivery confirmed by persisted marketplace lifecycle' : 'Delivery not confirmed';
    }

    function marketplacePromiseHtml(cell) {
        if (!cell) return '';
        const label = Array.from(cell.querySelectorAll('.small.text-muted')).find(node => /marketplace promise/i.test(String(node.textContent || '')));
        if (!label) return '';
        const service = label.nextElementSibling;
        if (!service || service.tagName !== 'STRONG') return '';
        return '<div class="small text-muted">Marketplace promise</div><strong>' + service.innerHTML + '</strong>';
    }

    function alignShipping(row, status) {
        const cell = row.children && row.children[5];
        if (!cell) return;
        const promise = marketplacePromiseHtml(cell);
        if (!promise) return;

        if (dispatchedStates.has(status)) {
            // Once dispatch truth exists, route-choice badges are historical/no
            // longer actionable. The physical carrier/tracking remains in the
            // Shipment column; this cell is marketplace promise only.
            cell.innerHTML = promise;
            return;
        }

        // Pre-dispatch: remove the false generic Marketplace / Packlink / Manual
        // route claims. The governed recommendation path can fill the actual
        // carrier once parcel, saved rate and user-confirmed cutoff are available.
        cell.innerHTML = promise +
            '<div class="mt-2"><div class="small text-muted">Recommended shipping</div>' +
            '<strong class="bt38-recommended-shipping-state">Pending automatic selection</strong></div>';
    }

    function alignRows() {
        document.querySelectorAll('.fbm-order-row').forEach(row => {
            const status = String(row.dataset.lifecycleStatus || '').trim().toLowerCase();
            alignJourney(row, status);
            alignShipping(row, status);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', alignRows, {once: true});
    } else {
        alignRows();
    }
    window.addEventListener('bt38-marketplace-event', () => window.requestAnimationFrame(alignRows));
})(document);
