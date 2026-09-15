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

  function localDay(value) {
    if (!value) return null;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return null;
    return new Date(date.getFullYear(), date.getMonth(), date.getDate());
  }

  function historyBounds(session) {
    const range = allowedRanges.includes(String(session.range || session.historyRange || '').toLowerCase())
      ? String(session.range || session.historyRange).toLowerCase()
      : '3d';
    if (range === 'custom') {
      return {
        start: session.from ? new Date(String(session.from) + 'T00:00:00') : null,
        end: session.to ? new Date(String(session.to) + 'T23:59:59') : null
      };
    }
    const days = {'3d': 3, '7d': 7, '30d': 30, '90d': 90, '1y': 365}[range] || 3;
    const now = new Date();
    const end = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59, 999);
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    start.setDate(start.getDate() - (days - 1));
    return {start: start, end: end};
  }

  function rowInHistory(row, session) {
    const date = localDay(row.dataset.fbmCreatedAt || '');
    if (!date) return false;
    const bounds = historyBounds(session);
    if (bounds.start && date < bounds.start) return false;
    if (bounds.end && date > bounds.end) return false;
    return true;
  }

  function syncHistoryControls() {
    const form = document.getElementById('bt38FbmControls');
    const range = document.getElementById('bt38FbmRangeSelect') || document.getElementById('bt38FbmRange');
    const from = document.getElementById('bt38FbmFrom');
    const to = document.getElementById('bt38FbmTo');
    if (!form || !range) return;

    form.removeAttribute('onsubmit');
    range.removeAttribute('onchange');
    if (from) from.removeAttribute('onchange');
    if (to) to.removeAttribute('onchange');

    function showCustom() {
      const custom = range.value === 'custom';
      if (from) from.style.display = custom ? '' : 'none';
      if (to) to.style.display = custom ? '' : 'none';
    }

    function applyLocalHistory(event) {
      if (event) {
        event.preventDefault();
        event.stopPropagation();
      }
      const selected = allowedRanges.includes(range.value) ? range.value : '3d';
      const next = {
        historyRange: selected,
        range: selected,
        from: from ? from.value : '',
        to: to ? to.value : ''
      };
      setSessionState(next);
      try {
        sessionStorage.setItem('bt38_fbm_range', selected);
        sessionStorage.setItem('bt38_fbm_from', next.from);
        sessionStorage.setItem('bt38_fbm_to', next.to);
      } catch (_) {}
      showCustom();
      alignAllRowVisibility();
    }

    showCustom();
    if (!form.dataset.bt38FbmLocalBound) {
      form.dataset.bt38FbmLocalBound = '1';
      form.addEventListener('submit', applyLocalHistory, true);
    }
    if (!range.dataset.bt38FbmBound) {
      range.dataset.bt38FbmBound = '1';
      range.addEventListener('change', applyLocalHistory, true);
    }
    if (from && !from.dataset.bt38FbmBound) {
      from.dataset.bt38FbmBound = '1';
      from.addEventListener('change', applyLocalHistory, true);
    }
    if (to && !to.dataset.bt38FbmBound) {
      to.dataset.bt38FbmBound = '1';
      to.addEventListener('change', applyLocalHistory, true);
    }
  }

  function syncPageSize() {
    const select = document.getElementById('bt38ResultsPerPageSelect');
    if (!select) return;
    select.removeAttribute('onchange');

    const rendered = Number.parseInt(select.value, 10);
    const pageSize = allowedPageSizes.includes(rendered) ? rendered : 15;
    if (select.value !== String(pageSize)) select.value = String(pageSize);
    setSessionState({pageSize: pageSize});
    try { sessionStorage.setItem('bt38_fbm_limit', String(pageSize)); } catch (_) {}

    if (!select.dataset.bt38FbmSessionBound) {
      select.dataset.bt38FbmSessionBound = '1';
      select.addEventListener('change', function (event) {
        event.preventDefault();
        event.stopPropagation();
        const selected = Number.parseInt(select.value, 10);
        const normalized = allowedPageSizes.includes(selected) ? selected : 15;
        setSessionState({pageSize: normalized});
        try { sessionStorage.setItem('bt38_fbm_limit', String(normalized)); } catch (_) {}
        alignAllRowVisibility();
      }, true);
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
      state.currentPage = 1;
    }
  }

  function rowMatchesSession(row, session) {
    if (!row || !row.classList || !row.classList.contains('fbm-order-row')) return false;
    if (!rowInHistory(row, session)) return false;
    const activeTab = String(session.tab || 'pending');
    const search = String(session.search || '').trim().toLowerCase();
    const queue = String(row.dataset.fbmQueue || '');
    const searchText = String(row.dataset.fbmSearch || row.textContent || '').toLowerCase();
    if (queue && queue !== activeTab) return false;
    return !search || searchText.indexOf(search) >= 0;
  }

  function alignAllRowVisibility() {
    if (!onFbm()) return;
    bindPagerToCommittedSnapshot();
    const session = getSessionState({tab: 'pending', search: '', range: '3d', from: '', to: '', pageSize: 15});
    const matched = [];
    document.querySelectorAll('tr.fbm-order-row').forEach(function (row) {
      const show = rowMatchesSession(row, session);
      row.dataset.fbmHistoryMatch = rowInHistory(row, session) ? '1' : '0';
      row.hidden = !show;
      if (show) matched.push(row);
    });

    const pages = window.BT38 && window.BT38.pages;
    const state = pages && (pages.fbm || pages.FBM);
    const controller = window.BT38 && window.BT38.PageController;
    if (state && Array.isArray(state.rows) && controller && typeof controller.renderPage === 'function') {
      const matchedSet = new Set(matched);
      state.filteredRows = state.rows.filter(function (entry) {
        return entry && matchedSet.has(entry.el);
      });
      state.currentPage = 1;
      controller.renderPage(state.name);
    }
  }

  function bindLifecycleControls() {
    document.querySelectorAll('.fbm-lifecycle-tab[data-fbm-tab]').forEach(function (button) {
      if (button.dataset.bt38SessionBound) return;
      button.dataset.bt38SessionBound = '1';
      button.addEventListener('click', function () {
        setSessionState({tab: String(button.dataset.fbmTab || 'pending')});
        alignAllRowVisibility();
      });
    });

    const fba = Array.from(document.querySelectorAll('a.fbm-lifecycle-tab')).find(function (link) {
      return String(link.getAttribute('href') || '') === '/governed/amazon-fba-stock';
    });
    if (fba && !fba.dataset.bt38FbaNavBound) {
      fba.dataset.bt38FbaNavBound = '1';
      fba.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopImmediatePropagation();
        window.location.assign('/governed/amazon-fba-stock');
      }, true);
    }
  }

  function bindSearch() {
    const input = document.getElementById('bt38FbmGlobalSearchInput');
    const clear = document.getElementById('bt38FbmGlobalSearchClear');
    if (input && !input.dataset.bt38SessionBound) {
      input.dataset.bt38SessionBound = '1';
      input.addEventListener('input', function () {
        setSessionState({search: String(input.value || '').trim().toLowerCase()});
        alignAllRowVisibility();
      }, true);
    }
    if (clear && !clear.dataset.bt38SessionBound) {
      clear.dataset.bt38SessionBound = '1';
      clear.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        if (input) input.value = '';
        setSessionState({search: ''});
        alignAllRowVisibility();
      }, true);
    }
  }

  function restoreLifecycleTab() {
    if (!onFbm()) return;
    const session = getSessionState({tab: 'pending'});
    const activeTab = String(session.tab || 'pending');
    const selectedTab = document.querySelector('.fbm-lifecycle-tab[data-fbm-tab="' + activeTab + '"]')
      || document.querySelector('.fbm-lifecycle-tab[data-fbm-tab="pending"]');
    if (selectedTab && !selectedTab.classList.contains('active')) selectedTab.click();
  }

  function initialise() {
    if (!onFbm()) return;
    syncHistoryControls();
    syncPageSize();
    bindLifecycleControls();
    bindSearch();
    bindPagerToCommittedSnapshot();
    restoreLifecycleTab();
    alignAllRowVisibility();
    window.addEventListener('load', function () {
      syncHistoryControls();
      syncPageSize();
      bindLifecycleControls();
      bindSearch();
      alignAllRowVisibility();
    }, {once: true});
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialise, {once: true});
  } else {
    initialise();
  }
})();
