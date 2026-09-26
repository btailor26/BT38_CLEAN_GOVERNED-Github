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

    function performanceState(row) {
        return String(row?.dataset?.deliveryPerformance || '').trim().toLowerCase();
    }

    function persistedMilestones(row) {
        // Single display authority: Tracking history. Shipment journey is only
        // a summary/classification of these exact same persisted events.
        const events = trackingEvents(row).map(function (event) {
            const status = String(event && event.status || '').trim().toLowerCase().replace(/[ -]+/g, '_');
            const text = [event && event.status, event && event.description, event && event.detail]
                .filter(Boolean).join(' ').toLowerCase();
            const time = String(event && (event.event_time || event.observed_at) || '');
            return {event: event, status: status, text: text, time: time};
        }).sort(function (a, b) {
            return (new Date(a.time || 0).getTime() || 0) - (new Date(b.time || 0).getTime() || 0);
        });
        const pickup = events.find(function (item) {
            return ['carrier_accepted', 'accepted', 'picked_up', 'collected', 'shipped'].includes(item.status) || /\b(we('|’)ve collected|collected your parcel|picked up|carrier accepted|shipment marked shipped|marked shipped)\b/.test(item.text);
        });
        const movement = events.find(function (item) {
            return ['in_transit', 'out_for_delivery'].includes(item.status) || /\b(in transit|out for delivery|on its way|arrived at your delivery depot|arrived at your delivery depot|arrived in our depot|national hub|we have your parcel|with one of our drivers)\b/.test(item.text);
        });
        const outForDelivery = events.find(function (item) {
            return item.status === 'out_for_delivery' || /\b(out for delivery|with one of our drivers|driver.*delivery)\b/.test(item.text);
        });
        const delivered = events.find(function (item) {
            return item.status === 'delivered' || /\b(parcel has been delivered|delivered)\b/.test(item.text);
        });
        // eBay Shipping can expose only two lifecycle facts: shipped and
        // delivered. A terminal delivery proves the parcel necessarily passed
        // through the earlier operational journey stages, without inventing
        // extra rows in Tracking history. Prefer the shipped timestamp for
        // Picked up; use delivery time only to confirm In transit when no
        // intermediate carrier movement event exists.
        return {
            pickedUp: Boolean(pickup || delivered), pickedUpAt: pickup ? pickup.time : '',
            inTransit: Boolean(movement || delivered), inTransitAt: movement ? movement.time : (delivered ? delivered.time : ''),
            outForDelivery: Boolean(outForDelivery), outForDeliveryAt: outForDelivery ? outForDelivery.time : '',
            delivered: Boolean(delivered), deliveredAt: delivered ? delivered.time : ''
        };
    }

    function deliveryProven(row) {
        // Persisted deliveredAt is the canonical terminal DB authority. The
        // persisted tracking event is the same factual delivery evidence used
        // by Tracking history; no weaker lifecycle or provider status may
        // promote a shipment to Delivered.
        const deliveredAt = String(row?.dataset?.deliveredAt || '').trim();
        return Boolean(deliveredAt) && persistedMilestones(row).delivered;
    }

    function performanceHtml(row) {
        const performance = performanceState(row);
        if (performance === 'on_time') return '<span class="badge rounded-pill px-2 py-1 bg-success text-white">On time</span>';
        if (performance === 'late') return '<span class="badge rounded-pill px-2 py-1 bg-danger text-white">Late</span>';
        if (performance === 'timing_unavailable') return '<span class="badge rounded-pill px-2 py-1 bg-secondary text-white">Delivered · timing unavailable</span>';
        return '';
    }

    function promiseHtml(row) {
        const shipBy = displayDate(row?.dataset?.shipByAt || '');
        const deliverBy = displayDate(row?.dataset?.deliveryPromiseAt || '');
        if (!shipBy && !deliverBy) return '<div class="text-muted small">Marketplace delivery promise unavailable in persisted BT38 DB.</div>';
        return `<div class="small text-muted mb-1">Marketplace promise · persisted BT38 DB</div>${shipBy ? `<div class="small"><strong>Ship by:</strong> ${esc(shipBy)}</div>` : ''}${deliverBy ? `<div class="small"><strong>Deliver by:</strong> ${esc(deliverBy)}</div>` : ''}`;
    }

    function stateBadge(confirmed) {
        return confirmed
            ? '<span class="badge rounded-pill px-2 py-1 text-center bg-success text-white border border-success" style="min-width:88px">Confirmed</span>'
            : '<span class="badge rounded-pill px-2 py-1 text-center bg-light text-muted border border-secondary" style="min-width:88px">Pending</span>';
    }

    function milestoneHtml(row) {
        const carrier = String(row?.dataset?.carrier || '').trim() || 'Carrier';
        const milestones = persistedMilestones(row);
        const pickedUpAt = milestones.pickedUpAt;
        const movementAt = milestones.inTransitAt;
        const deliveredAt = milestones.deliveredAt;
        const pickupPassed = milestones.pickedUp;
        const transitPassed = milestones.inTransit;
        const delivered = deliveryProven(row);

        function milestone(title, confirmed, exactTime) {
            const border = confirmed ? 'border-success' : 'border-secondary';
            const detail = exactTime ? `<div class="small text-muted">${esc(displayDate(exactTime))}</div>` : '';
            return `<div class="border-start border-3 ${border} ps-3 py-2 mb-2"><div class="d-flex justify-content-between align-items-start gap-3"><div><div class="fw-semibold">${esc(title)}</div>${detail}</div>${stateBadge(confirmed)}</div></div>`;
        }

        if (!pickupPassed && !transitPassed && !delivered) {
            return '<div class="alert alert-light border mb-2"><div class="fw-semibold">Waiting for carrier update</div><div class="small text-muted mt-1">No carrier tracking movement has been received yet.</div></div>';
        }
        return milestone('Picked up', pickupPassed, pickedUpAt) +
            milestone('In transit', transitPassed, movementAt) +
            milestone('Delivered', delivered, deliveredAt);
    }

    function trackingEvents(row) {
        const raw = String(row?.dataset?.trackingEvents || '').trim();
        if (!raw) return [];
        try {
            const parsed = JSON.parse(raw);
            return Array.isArray(parsed) ? parsed : [];
        } catch (_error) {
            return [];
        }
    }

    function packageSummaryHtml(events, providerReference) {
        const latestWithMeta = [...events].reverse().find(function (event) {
            return event && (event.estimated_delivery_at || event.package_count || event.package_data);
        }) || null;
        const eta = latestWithMeta ? displayDate(latestWithMeta.estimated_delivery_at || '') : '';
        const count = latestWithMeta && Number.isFinite(Number(latestWithMeta.package_count)) ? Number(latestWithMeta.package_count) : null;
        if (!providerReference && !eta && count === null) return '';
        return `<div class="border rounded p-3 mb-3">` +
            `${providerReference ? `<div class="small text-muted">Shipment reference</div><div class="fw-semibold mb-2">${esc(providerReference)}</div>` : ''}` +
            `${count !== null ? `<div class="small"><strong>${count === 1 ? 'Single package' : `${esc(count)} packages`}</strong> · ${esc(count)} package${count === 1 ? '' : 's'} in the shipment</div>` : ''}` +
            `${eta ? `<div class="small mt-2"><strong>Estimated delivery:</strong> ${esc(eta)}</div>` : ''}` +
            `</div>`;
    }

    function trackingHistoryHtml(events) {
        if (!events.length) return '<div class="small text-muted">No detailed carrier scan history has been persisted yet.</div>';
        const ordered = [...events].sort(function (a, b) {
            const aTime = new Date(a.event_time || a.observed_at || 0).getTime() || 0;
            const bTime = new Date(b.event_time || b.observed_at || 0).getTime() || 0;
            return bTime - aTime;
        });
        return `<div class="fw-semibold mt-3 mb-2">Tracking history</div><div class="list-group list-group-flush border rounded">` + ordered.map(function (event, index) {
            const when = displayDate(event.event_time || '');
            const title = String(event.description || event.status || '').trim();
            const detail = String(event.detail || '').trim();
            const location = String(event.location || '').trim();
            if (!title && !detail && !location) return '';
            return `<div class="list-group-item py-2"><div class="d-flex justify-content-between gap-3"><div>${title ? `<div class="fw-semibold">${esc(title)}</div>` : ''}${detail ? `<div class="small text-muted">${esc(detail)}</div>` : ''}${location ? `<div class="small text-muted">${esc(location)}</div>` : ''}</div>${index === 0 ? '<span class="badge rounded-pill px-2 py-1 bg-secondary text-white align-self-start">Latest</span>' : ''}</div>${when ? `<div class="small text-muted mt-1">${esc(when)}</div>` : ''}</div>`;
        }).join('') + `</div>`;
    }

    function shippingCostText(row) {
        const raw = String(row?.dataset?.shippingCost || '').trim();
        if (!raw) return '';
        const amount = Number(raw);
        if (!Number.isFinite(amount)) return '';
        const currency = String(row?.dataset?.shippingCostCurrency || '').trim().toUpperCase();
        const symbol = currency === 'GBP' ? '£' : currency === 'EUR' ? '€' : currency === 'USD' ? '$' : (currency ? currency + ' ' : '');
        return symbol + amount.toFixed(2);
    }

    function alignShippingAndShipment(row) {
        const shippingCell = row?.children?.[5] || null;
        const shipmentCell = row?.children?.[7] || null;
        const shippingSource = String(row?.dataset?.shippingSource || '').trim();
        const carrier = String(row?.dataset?.carrier || '').trim();
        const shippingCost = shippingCostText(row);
        if (shippingCell) shippingCell.innerHTML = (shippingSource ? `<strong>${esc(shippingSource)}</strong>` : '<span class="text-muted">—</span>') + (shippingCost ? `<div class="small fw-semibold mt-1">Cost: ${esc(shippingCost)}</div>` : '<div class="small text-muted mt-1">Cost: not recovered</div>');
        if (shipmentCell) {
            let carrierNode = shipmentCell.querySelector('strong');
            if (!carrierNode) { carrierNode = document.createElement('strong'); shipmentCell.insertBefore(carrierNode, shipmentCell.firstChild); }
            carrierNode.textContent = carrier || '—';
            if (!carrier) carrierNode.classList.add('text-muted');
            shipmentCell.querySelectorAll('.badge').forEach(function (badge) { if (String(badge.textContent || '').trim().toLowerCase() === 'marketplace') badge.remove(); });
            Array.from(shipmentCell.childNodes).forEach(function (node) { if (node.nodeType === Node.TEXT_NODE && /marketplace says shipped/i.test(node.textContent || '')) node.remove(); });
        }
    }

    function alignJourneyRowColours(row) {
        const journeyCell = row?.children?.[8] || null;
        if (!journeyCell) return;
        const terminalDelivery = deliveryProven(row);
        const milestones = persistedMilestones(row);
        const stageTruth = {
            'picked up': milestones.pickedUp,
            'in transit': milestones.inTransit,
            'delivered': deliveryProven(row)
        };
        Array.from(journeyCell.querySelectorAll('.badge')).forEach(function (badge) {
            const label = String(badge.textContent || '').trim().toLowerCase();
            if (!(label in stageTruth)) return;
            badge.classList.remove('bg-success', 'bg-danger', 'bg-secondary', 'bg-light', 'text-muted', 'text-dark', 'border', 'border-success', 'border-danger', 'border-secondary');
            if (stageTruth[label]) {
                badge.classList.add('bg-success', 'text-white');
            } else {
                badge.classList.add('bg-light', 'text-muted', 'border', 'border-secondary');
            }
        });
        Array.from(journeyCell.querySelectorAll('.fbm-row-note')).forEach(function (note) {
            const text = String(note.textContent || '');
            if (milestones.pickedUp && /pickup not confirmed/i.test(text)) note.remove();
            if (terminalDelivery && /carrier pickup overdue/i.test(text)) note.remove();
        });
    }

    function alignPromisePerformance(row) {
        const promiseCell = row?.querySelector?.('.fbm-promise-cell') || null;
        if (!promiseCell) return;
        let holder = promiseCell.querySelector('.fbm-delivery-performance');
        if (!holder) {
            holder = document.createElement('div');
            holder.className = 'fbm-delivery-performance mt-1';
            promiseCell.appendChild(holder);
        }
        // One authority: the same persisted delivery-performance state supplies
        // both the text and Bootstrap colour class. Never infer colour separately.
        holder.innerHTML = performanceHtml(row);
    }

    function alignRowPerformance(row) {
        alignShippingAndShipment(row);
        alignJourneyRowColours(row);
        alignPromisePerformance(row);
    }

    function openAlignedJourney(button) {
        const row = button.closest('.fbm-order-row');
        const modalElement = document.getElementById('fbmTrackingJourneyModal');
        const body = document.getElementById('fbmTrackingJourneyBody');
        const subtitle = document.getElementById('fbmTrackingJourneySubtitle');
        if (!row || !modalElement || !body) return;
        const tracking = button.dataset.trackingNumber || row.dataset.trackingNumber || String(button.textContent || '').trim() || '—';
        const shipmentCell = row.children?.[7] || null;
        const carrier = String(row.dataset.carrier || '').trim() || '—';
        const providerReference = String(row.dataset.providerShipmentId || '').trim();
        const events = trackingEvents(row);
        if (subtitle) subtitle.textContent = tracking;
        const shippingSource = String(row.dataset.shippingSource || '').trim() || 'Persisted shipment';
        body.innerHTML = `<div class="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-3"><div><div class="fw-semibold">${esc(carrier)}</div><div class="small">Tracking: <code>${esc(tracking)}</code></div><div class="small text-muted">Tracking authority: ${esc(shippingSource)} · persisted BT38 DB</div></div><div>${performanceHtml(row)}</div></div>` + packageSummaryHtml(events, providerReference) + `<div class="border rounded p-3 mb-3">${promiseHtml(row)}</div><div class="fw-semibold mb-2">Shipment journey</div>${milestoneHtml(row)}` + trackingHistoryHtml(events);
        bootstrap.Modal.getOrCreateInstance(modalElement).show();
    }

    function intercept(event) {
        const button = event.target && event.target.closest ? event.target.closest(TRACKING_TRIGGER_SELECTOR) : null;
        if (!button) return;
        event.preventDefault(); event.stopPropagation(); event.stopImmediatePropagation(); openAlignedJourney(button);
    }

    function install() {
        if (document.documentElement.dataset.bt38PromiseJourneyAligned === '15') return;
        document.documentElement.dataset.bt38PromiseJourneyAligned = '15';
        document.querySelectorAll('.fbm-order-row').forEach(alignRowPerformance);
        window.addEventListener('click', intercept, true);
        window.addEventListener('keydown', function (event) { if (event.key !== 'Enter' && event.key !== ' ') return; intercept(event); }, true);
        document.addEventListener('fbm:rows-updated', function () { document.querySelectorAll('.fbm-order-row').forEach(alignRowPerformance); });
        document.addEventListener('bt38-fbm-committed-snapshot-applied', function (event) {
            const orderId = String(event?.detail?.order_id || event?.detail?.orderId || '').trim();
            if (!orderId) return;
            const row = document.querySelector('.fbm-order-row[data-order-id="' + CSS.escape(orderId) + '"]');
            if (row) alignRowPerformance(row);
        });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install, {once: true});
    else install();
})();
