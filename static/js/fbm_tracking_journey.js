/* BT38 FBM asset alignment bootstrap.
 * Load native eBay shipping before the preserved tracking journey so the
 * capture-phase native handler owns eBay Shipping and the legacy Seller Hub
 * handler cannot run first.
 *
 * Journey colour rule:
 * - persisted label/postage created without carrier acceptance => Picked up RED
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

    const pickupStates = new Set([
        'accepted',
        'carrier_accepted',
        'collected',
        'picked_up',
        'in_transit',
        'out_for_delivery',
        'delivered'
    ]);
    const movementStates = new Set(['in_transit', 'out_for_delivery', 'delivered']);

    function lifecycleLabel(status) {
        const labels = {
            pending: 'Pending',
            unshipped: 'Confirmed',
            order: 'Confirmed',
            confirmed: 'Confirmed',
            partially_shipped: 'Partially dispatched',
            shipped: 'Dispatched',
            accepted: 'Picked up',
            carrier_accepted: 'Picked up',
            collected: 'Picked up',
            picked_up: 'Picked up',
            in_transit: 'In transit',
            out_for_delivery: 'Out for delivery',
            delivered: 'Delivered',
            return_requested: 'Return requested',
            returned: 'Returned',
            refund_requested: 'Refund requested',
            refunded: 'Refunded',
            replacement_requested: 'Replacement requested',
            replacement: 'Replacement',
            case_open: 'Issue / case',
            dispute: 'Dispute',
            chargeback: 'Chargeback',
            cancel_requested: 'Cancellation requested',
            cancelled: 'Cancelled'
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

    function setBadgeState(badge, stateClass) {
        if (!badge) return;
        badge.classList.remove('bg-success', 'bg-danger', 'bg-primary', 'bg-light', 'text-muted', 'text-dark', 'border');
        String(stateClass || '').split(/\s+/).filter(Boolean).forEach(name => badge.classList.add(name));
    }

    function alignPersistedLifecycle() {
        // Search, history, lifecycle tabs and pagination are owned by the existing
        // FBM session/page controller. This journey bootstrap must not create a
        // second search form, pager, row filter or page-size authority.
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

            const journeyCell = row.children && row.children[8];
            if (!journeyCell) return;
            const badges = Array.from(journeyCell.querySelectorAll('.badge'));
            const pickedUp = badges.find(badge => /picked up/i.test(String(badge.textContent || '')));
            const inTransit = badges.find(badge => /in transit/i.test(String(badge.textContent || '')));
            const delivered = badges.find(badge => /delivered/i.test(String(badge.textContent || '')));

            const pickupAlreadyConfirmed = Boolean(pickedUp && pickedUp.classList.contains('bg-success'));
            if (pickupAlreadyConfirmed || pickupStates.has(status)) {
                setBadgeState(pickedUp, 'bg-success');
                if (pickedUp) pickedUp.title = 'Carrier pickup confirmed by persisted journey state';
            } else if (labelOrTrackingStageReached(row)) {
                setBadgeState(pickedUp, 'bg-danger');
                if (pickedUp) pickedUp.title = 'Label / postage created · waiting for carrier collection';
            }

            if (movementStates.has(status)) setBadgeState(inTransit, 'bg-success');
            if (status === 'delivered' && delivered && !delivered.classList.contains('bg-danger')) {
                setBadgeState(delivered, 'bg-success');
            }
        });
    }

    let governedLiveRefreshPending = false;

    async function applyCommittedFbmSnapshot() {
        if (governedLiveRefreshPending) return;
        governedLiveRefreshPending = true;
        try {
            const response = await fetch(window.location.href, {
                method: 'GET',
                credentials: 'same-origin',
                cache: 'no-store',
                headers: {'Accept': 'text/html'}
            });
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
                if (freshRow.dataset.lifecycleStatus) row.dataset.lifecycleStatus = freshRow.dataset.lifecycleStatus;
                row.dataset.labelReady = freshRow.dataset.labelReady || '0';
            });
            window.BT38FBMApplyCommittedSnapshot(nextData, nextCounts);
            alignPersistedLifecycle();
        } catch (error) {
            console.warn('[BT38 FBM] committed session refresh unavailable', error);
        } finally {
            governedLiveRefreshPending = false;
        }
    }

    function refreshFbmFromGovernedEvent() {
        // Reuse the application shell's single governed SSE connection. This is
        // one event-driven DB snapshot read after commit: no poller, no second
        // EventSource, no marketplace/provider read and no full-page refresh.
        const activeModal = document.querySelector('#fbmShippingModal.show, #fbmTrackingJourneyModal.show');
        if (activeModal) {
            activeModal.addEventListener('hidden.bs.modal', () => void applyCommittedFbmSnapshot(), {once: true});
            return;
        }
        void applyCommittedFbmSnapshot();
    }

    window.addEventListener('bt38-marketplace-event', refreshFbmFromGovernedEvent);

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
        legacy.onload = function () {
            alignPersistedLifecycle();
            loadDeliveryPromiseAlignment();
        };
        legacy.onerror = function () {
            alignPersistedLifecycle();
            loadDeliveryPromiseAlignment();
        };
        document.head.appendChild(legacy);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', alignPersistedLifecycle, {once: true});
    } else {
        alignPersistedLifecycle();
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
