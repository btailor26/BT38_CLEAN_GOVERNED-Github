// FBM browser-session presentation alignment.
// No polling or marketplace/provider reads are owned here. The server renders
// the explicitly selected 15/30/50/100 order window; explicit user controls
// submit one native GET event only when a different persisted dataset is needed.
// With no event, the FBM session sleeps.
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

  function submitControls(form) {
    if (!form) return;
    // This is an explicit user GET. Use the form's native submit path so no
    // other submit-event controller can delay or cancel the timeframe refresh.
    form.submit();
  }

  function syncHistoryControls() {
    const form = document.getElementById('bt38FbmControls');
    const range = document.getElementById('bt38FbmRange');
    const from = document.getElementById('bt38FbmFrom');
    const to = document.getElementById('bt38FbmTo');
    if (!form || !range) return;

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
        setSessionState({historyRange: selected});
        try { sessionStorage.setItem('bt38_fbm_range', selected); } catch (_) {}
        showCustom();
        if (selected !== 'custom') submitControls(form);
      });
    }

    if (from && !from.dataset.bt38FbmBound) {
      from.dataset.bt38FbmBound = '1';
      from.addEventListener('change', function () {
        try { sessionStorage.setItem('bt38_fbm_from', from.value); } catch (_) {}
      });
    }
    if (to && !to.dataset.bt38FbmBound) {
      to.dataset.bt38FbmBound = '1';
      to.addEventListener('change', function () {
        try { sessionStorage.setItem('bt38_fbm_to', to.value); } catch (_) {}
      });
    }
  }

  function syncPageSize() {
    const select = document.getElementById('bt38ResultsPerPageSelect');
    const form = document.getElementById('bt38FbmControls');
    if (!select) return;

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
        submitControls(form || select.form);
      });
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
    restoreLifecycleTab();
    alignAllRowVisibility();
    window.addEventListener('load', function () {
      syncHistoryControls();
      syncPageSize();
      alignAllRowVisibility();
    }, {once: true});
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialise, {once: true});
  } else {
    initialise();
  }
})();
