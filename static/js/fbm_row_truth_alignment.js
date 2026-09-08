/* Presentation-only FBM row truth alignment.
 * Uses only data already rendered into the row. No fetch, DB read, provider call,
 * polling, timer or marketplace action is allowed here.
 */
(function (document) {
    'use strict';

    const pickupStates = new Set(['accepted', 'carrier_accepted', 'collected', 'picked_up']);
    const movementStates = new Set(['in_transit', 'out_for_delivery']);

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

    function renderedRecommendation(cell) {
        if (!cell) return '';

        // When a marketplace promise was rendered, the existing governed route
        // recommendation is already present in the row as "Route: ...". Use it;
        // never replace it with a synthetic pending state.
        const routeNote = Array.from(cell.querySelectorAll('.fbm-row-note')).find(node => /^\s*Route\s*:/i.test(String(node.textContent || '')));
        if (routeNote) {
            return String(routeNote.textContent || '').replace(/^\s*Route\s*:\s*/i, '').trim();
        }

        // When there is no marketplace service, the template already renders the
        // existing recommendation directly as the primary strong value.
        const promiseLabel = Array.from(cell.querySelectorAll('.small.text-muted')).find(node => /marketplace promise/i.test(String(node.textContent || '')));
        const promiseValue = promiseLabel && promiseLabel.nextElementSibling && promiseLabel.nextElementSibling.tagName === 'STRONG'
            ? promiseLabel.nextElementSibling
            : null;
        const primary = Array.from(cell.querySelectorAll('strong')).find(node => node !== promiseValue);
        return primary ? String(primary.textContent || '').trim() : '';
    }

    function removeMarketplacePromise(cell) {
        if (!cell) return;
        const label = Array.from(cell.querySelectorAll('.small.text-muted')).find(node => /marketplace promise/i.test(String(node.textContent || '')));
        if (!label) return;
        const service = label.nextElementSibling;
        if (service && service.tagName === 'STRONG') service.remove();
        label.remove();
    }

    function alignShipping(row, status) {
        const cell = row.children && row.children[5];
        if (!cell) return;

        const recommendation = renderedRecommendation(cell);

        // Marketplace shipping-service metadata is not physical shipment/label
        // authority. Keep delivery dates in the promise column, but remove the
        // marketplace service from this shipping cell so it cannot be mistaken
        // for the purchased-label carrier/service.
        removeMarketplacePromise(cell);

        // Remove the old route note after capturing its existing governed value.
        Array.from(cell.querySelectorAll('.fbm-row-note')).forEach(node => {
            if (/^\s*Route\s*:/i.test(String(node.textContent || ''))) node.remove();
        });

        // Dispatched rows get their physical carrier/service from the Shipment
        // column. Do not re-label historical marketplace service as shipment truth.
        if (['shipped', 'partially_shipped', 'partiallyshipped', 'accepted', 'carrier_accepted', 'collected', 'picked_up', 'in_transit', 'out_for_delivery', 'delivered'].includes(status)) {
            return;
        }

        // Pre-dispatch rows must surface the recommendation already rendered by
        // the governed shipping path. Never overwrite it with a locked
        // "Pending automatic selection" placeholder.
        if (recommendation) {
            cell.innerHTML = '<div class="small text-muted">Recommended shipping</div>' +
                '<strong class="bt38-recommended-shipping-state"></strong>';
            const value = cell.querySelector('.bt38-recommended-shipping-state');
            if (value) value.textContent = recommendation;
        }
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
