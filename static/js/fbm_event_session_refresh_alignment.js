// FBM browser-session presentation alignment.
// No polling or marketplace/provider reads are owned here.  The server renders
// the explicitly selected 15/30/50/100 order window; browser session state only
// remembers presentation choices and local workflow/search state.
(function () {
  'use strict';
  if (window.bt38FbmEventSessionRefreshInstalled) return;
  window.bt38FbmEventSessionRefreshInstalled = true;

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

  function syncPageSize() {
    const select = document.getElementById('bt38ResultsPerPageSelect');
    if (!select) return;

    // The server value is authoritative because it controls how many rows were
    // actually read from Neon.  Do not make a 15-row DOM pretend it contains 30,
    // 50 or 100 rows.  Persist the server-selected value for browser continuity.
    const rendered = Number.parseInt(select.value, 10);
    const pageSize = allowedPageSizes.includes(rendered) ? rendered : 15;
    if (select.value !== String(pageSize)) select.value = String(pageSize);
    setSessionState({pageSize});

    if (!select.dataset.bt38FbmSessionBound) {
      select.dataset.bt38FbmSessionBound = '1';
      select.addEventListener('change', function () {
        const selected = Number.parseInt(select.value, 10);
        const normalized = allowedPageSizes.includes(selected) ? selected : 15;
        setSessionState({pageSize: normalized});
        // The select lives inside bt38FbmHistoryControls and its inline onchange
        // submits that GET form.  That explicit user action is the only time a
        // wider order window is read from Neon.
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
    syncPageSize();
    restoreLifecycleTab();
    alignAllRowVisibility();
    window.addEventListener('load', function () {
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
