// FBM browser-session presentation alignment.
// No polling or marketplace/provider reads are owned here. History, lifecycle,
// search and page-size controls operate only on the maintained FBM page/session
// working set. With no event, the FBM session sleeps.
(function () {
  'use strict';
  if (window.bt38FbmEventSessionRefreshInstalled) return;
  window.bt38FbmEventSessionRefreshInstalled = true;

  const allowedPageSizes = [15, 30, 50, 100];
  const allowedRanges = ['3d', '7d', '30d', '90d', '1y', 'custom'];

  function onFbm() {
    return String(window.location.pathname || '').replace(/\/$/, '') === '/fbm';
  }

  function getSessionState(defaults) {
    if (window.BT38 && typeof window.BT38.getPageSession === 'function') {
      return window.BT38.getPageSession('fbm', defaults || {});
    }
    return Object.assign({}, defaults || {});
  }

  function setSessionState(values) {
    if (window.BT38 && typeof window.BT38.setPageSession === 'function') {
      return window.BT38.setPageSession('fbm', values || {});
    }
    return values || {};
  }

  function syncHistoryControls() {
    const form = document.getElementById('bt38FbmControls');
    const range = document.getElementById('bt38FbmRangeSelect') || document.getElementById('bt38FbmRange');
    const from = document.getElementById('bt38FbmFrom');
    const to = document.getElementById('bt38FbmTo');
    if (!form || !range) return;

    // Legacy server controls used inline form.submit(). FBM filtering is now a
    // presentation concern, so those attributes must never escape to /fbm.
    form.removeAttribute('onsubmit');
    range.removeAttribute('onchange');
    if (from) from.removeAttribute('onchange');
    if (to) to.removeAttribute('onchange');

    function showCustom() {
      const custom = range.value === 'custom';
      if (from) from.style.display = custom ? '' : 'none';
      if (to) to.style.display = custom ? '' : 'none';
    }

    showCustom();
    if (!range.dataset.bt38FbmBound) {
      range.dataset.bt38FbmBound = '1';
      range.addEventListener('change', function () {
        const selected = allowedRanges.includes(range.value) ? range.value : '3d';
        setSessionState({historyRange: selected, range: selected});
        try { sessionStorage.setItem('bt38_fbm_range', selected); } catch (_) {}
        showCustom();
        // governed_fbm_dispatch_queue_alignment owns the local history render.
        // Deliberately no form submission, network request, DB read or page reload here.
      });
    }

    if (from && !from.dataset.bt38FbmBound) {
      from.dataset.bt38FbmBound = '1';
      from.addEventListener('change', function () {
        setSessionState({from: from.value});
        try { sessionStorage.setItem('bt38_fbm_from', from.value); } catch (_) {}
      });
    }
    if (to && !to.dataset.bt38FbmBound) {
      to.dataset.bt38FbmBound = '1';
      to.addEventListener('change', function () {
        setSessionState({to: to.value});
        try { sessionStorage.setItem('bt38_fbm_to', to.value); } catch (_) {}
      });
    }
  }

  function syncPageSize() {
    const select = document.getElementById('bt38ResultsPerPageSelect');
    if (!select) return;

    // Page size is presentation only. Remove any retired server-submit hook;
    // bt38-page-controller.js renders the maintained local working set.
    select.removeAttribute('onchange');

    const rendered = Number.parseInt(select.value, 10);
    const pageSize = allowedPageSizes.includes(rendered) ? rendered : 15;
    if (select.value !== String(pageSize)) select.value = String(pageSize);
    setSessionState({pageSize});
    try { sessionStorage.setItem('bt38_fbm_limit', String(pageSize)); } catch (_) {}

    if (!select.dataset.bt38FbmSessionBound) {
      select.dataset.bt38FbmSessionBound = '1';
      select.addEventListener('change', function () {
        const selected = Number.parseInt(select.value, 10);
        const normalized = allowedPageSizes.includes(selected) ? selected : 15;
        setSessionState({pageSize: normalized});
        try { sessionStorage.setItem('bt38_fbm_limit', String(normalized)); } catch (_) {}
        // bt38-page-controller.js owns local pagination. No server request.
      });
    }
  }

  function committedSnapshotIds() {
    const node = document.getElementById('bt38FbmLifecycleTabsData');
    if (!node) return null;
    try {
      const payload = JSON.parse(node.textContent || '{}');
      return new Set(Object.keys(payload || {}));
    } catch (_) {
      return null;
    }
  }

  function bindPagerToCommittedSnapshot() {
    if (!onFbm()) return;
    const allowed = committedSnapshotIds();
    if (!allowed) return;

    document.querySelectorAll('tr.fbm-order-row').forEach(function (row) {
      if (!allowed.has(String(row.dataset.orderId || ''))) row.remove();
    });

    const pages = window.BT38 && window.BT38.pages;
    const state = pages && (pages.fbm || pages.FBM);
    if (state && Array.isArray(state.rows)) {
      state.rows = state.rows.filter(function (entry) {
        const row = entry && entry.el;
        return row && row.isConnected && allowed.has(String(row.dataset.orderId || ''));
      });
      if (Array.isArray(state.filteredRows)) {
        state.filteredRows = state.filteredRows.filter(function (entry) {
          const row = entry && entry.el;
          return row && row.isConnected && allowed.has(String(row.dataset.orderId || ''));
        });
      }
      state.currentPage = 1;
    }
  }

  function rowMatchesSession(row) {
    if (!row || !row.classList || !row.classList.contains('fbm-order-row')) return false;
    const session = getSessionState({tab: 'pending', search: ''});
    const activeTab = String(session && session.tab || 'pending');
    const search = String(session && session.search || '').trim().toLowerCase();
    const queue = String(row.dataset.fbmQueue || '');
    const searchText = String(row.dataset.fbmSearch || row.textContent || '').toLowerCase();
    if (!queue) return !search || searchText.indexOf(search) >= 0;
    return queue === activeTab && (!search || searchText.indexOf(search) >= 0);
  }

  function alignRowVisibility(row) {
    if (!row || !row.classList || !row.classList.contains('fbm-order-row')) return;
    if (!row.dataset.fbmQueue) return;
    const shouldShow = rowMatchesSession(row);
    row.hidden = !shouldShow;
    row.style.display = shouldShow ? '' : 'none';
  }

  function alignAllRowVisibility() {
    if (!onFbm()) return;
    bindPagerToCommittedSnapshot();
    document.querySelectorAll('tr.fbm-order-row').forEach(alignRowVisibility);
  }

  function restoreLifecycleTab() {
    if (!onFbm()) return;
    const session = getSessionState({tab: 'pending'});
    const activeTab = String(session && session.tab || 'pending');
    const selectedTab = document.querySelector('.fbm-lifecycle-tab[data-fbm-tab="' + activeTab + '"]')
      || document.querySelector('.fbm-lifecycle-tab[data-fbm-tab="pending"]');
    if (selectedTab && !selectedTab.classList.contains('active')) selectedTab.click();
  }

  function initialise() {
    if (!onFbm()) return;
    syncHistoryControls();
    syncPageSize();
    bindPagerToCommittedSnapshot();
    restoreLifecycleTab();
    alignAllRowVisibility();
    window.addEventListener('load', function () {
      syncHistoryControls();
      syncPageSize();
      bindPagerToCommittedSnapshot();
      alignAllRowVisibility();
    }, {once: true});
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialise, {once: true});
  } else {
    initialise();
  }
})();
