// FBM browser-session presentation alignment.
// No polling or marketplace/provider reads are owned here. History, lifecycle,
// search and existing pagination operate only on the maintained FBM page/session
// working set. With no event, the FBM session sleeps.
(function () {
  'use strict';
  if (window.bt38FbmEventSessionRefreshInstalled) return;
  window.bt38FbmEventSessionRefreshInstalled = true;

  const allowedRanges = ['3d', '7d', '30d', '90d', '1y', 'custom'];
  const allowedPageSizes = [15, 30, 50, 100];

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
        to: to ? to.value : '',
        currentPage: 1
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

  function renderLocalPage(matched, session) {
    const selectedSize = Number.parseInt(String(session.pageSize || 15), 10);
    const pageSize = allowedPageSizes.includes(selectedSize) ? selectedSize : 15;
    const totalPages = Math.max(1, Math.ceil(matched.length / pageSize));
    const requestedPage = Number.parseInt(String(session.currentPage || 1), 10) || 1;
    const currentPage = Math.min(Math.max(requestedPage, 1), totalPages);
    const start = (currentPage - 1) * pageSize;
    const end = Math.min(start + pageSize, matched.length);
    const visible = new Set(matched.slice(start, end));

    document.querySelectorAll('tr.fbm-order-row').forEach(function (row) {
      row.hidden = !visible.has(row);
    });

    const count = document.querySelector('#bt38FbmOrderFlow .bt38-table-count');
    if (count) count.textContent = matched.length + ' matching · showing ' + (matched.length ? start + 1 : 0) + '-' + end;
    const status = document.querySelector('#bt38FbmOrderFlow .bt38-page-status');
    if (status) status.textContent = 'Page ' + currentPage + ' of ' + totalPages + ' · ' + matched.length + ' total';
    const previous = document.getElementById('bt38FbmPreviousPage');
    const next = document.getElementById('bt38FbmNextPage');
    if (previous) previous.disabled = currentPage <= 1;
    if (next) next.disabled = currentPage >= totalPages;
    if (currentPage !== requestedPage) setSessionState({currentPage: currentPage});
  }

  function alignAllRowVisibility() {
    if (!onFbm()) return;
    const session = getSessionState({tab: 'pending', search: '', range: '3d', from: '', to: '', pageSize: 15, currentPage: 1});
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
      state.currentPage = Number.parseInt(String(session.currentPage || 1), 10) || 1;
      controller.renderPage(state.name);
    } else {
      renderLocalPage(matched, session);
    }
  }

  function bindLifecycleControls() {
    document.querySelectorAll('.fbm-lifecycle-tab[data-fbm-tab]').forEach(function (button) {
      if (button.dataset.bt38SessionBound) return;
      button.dataset.bt38SessionBound = '1';
      button.addEventListener('click', function () {
        setSessionState({tab: String(button.dataset.fbmTab || 'pending'), currentPage: 1});
        alignAllRowVisibility();
      });
    });
  }

  function bindSearch() {
    const input = document.getElementById('bt38FbmGlobalSearchInput');
    const clear = document.getElementById('bt38FbmGlobalSearchClear');
    if (input && !input.dataset.bt38SessionBound) {
      input.dataset.bt38SessionBound = '1';
      input.addEventListener('input', function () {
        setSessionState({search: String(input.value || '').trim().toLowerCase(), currentPage: 1});
        alignAllRowVisibility();
      }, true);
    }
    if (clear && !clear.dataset.bt38SessionBound) {
      clear.dataset.bt38SessionBound = '1';
      clear.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        if (input) input.value = '';
        setSessionState({search: '', currentPage: 1});
        alignAllRowVisibility();
      }, true);
    }
  }

  function bindOrderFlow() {
    const select = document.getElementById('bt38ResultsPerPageSelect');
    const previous = document.getElementById('bt38FbmPreviousPage');
    const next = document.getElementById('bt38FbmNextPage');
    const session = getSessionState({pageSize: 15, currentPage: 1});
    const savedSize = Number.parseInt(String(session.pageSize || 15), 10);
    if (select && allowedPageSizes.includes(savedSize)) select.value = String(savedSize);

    if (select && !select.dataset.bt38FbmBound) {
      select.dataset.bt38FbmBound = '1';
      select.addEventListener('change', function (event) {
        event.preventDefault();
        event.stopPropagation();
        const size = Number.parseInt(String(select.value || 15), 10);
        setSessionState({pageSize: allowedPageSizes.includes(size) ? size : 15, currentPage: 1});
        alignAllRowVisibility();
      }, true);
    }
    if (previous && !previous.dataset.bt38FbmBound) {
      previous.dataset.bt38FbmBound = '1';
      previous.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        const current = getSessionState({currentPage: 1});
        setSessionState({currentPage: Math.max(1, (Number.parseInt(String(current.currentPage || 1), 10) || 1) - 1)});
        alignAllRowVisibility();
      }, true);
    }
    if (next && !next.dataset.bt38FbmBound) {
      next.dataset.bt38FbmBound = '1';
      next.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        const current = getSessionState({currentPage: 1});
        setSessionState({currentPage: (Number.parseInt(String(current.currentPage || 1), 10) || 1) + 1});
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
    bindLifecycleControls();
    bindSearch();
    bindOrderFlow();
    restoreLifecycleTab();
    alignAllRowVisibility();
    window.addEventListener('load', function () {
      syncHistoryControls();
      bindLifecycleControls();
      bindSearch();
      bindOrderFlow();
      alignAllRowVisibility();
    }, {once: true});
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialise, {once: true});
  } else {
    initialise();
  }
})();
