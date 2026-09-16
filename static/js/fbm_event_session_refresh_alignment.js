// FBM browser-session refresh boundary.
//
// Ownership is intentionally narrow:
// - the existing FBM page/lifecycle controller owns history, tabs, search,
//   row visibility and pagination;
// - fbm_tracking_journey.js owns the single committed-event refresh handoff;
// - this file must not create another controller, pager, filter, timer, fetch,
//   marketplace read or EventSource.
//
// The active FBM tab/search/history remain stored by the existing page session
// owner (BT38.getPageSession / BT38.setPageSession). This file does not replay
// or override those controls.
//
// With no event, the FBM session sleeps.
(function () {
  'use strict';
  if (window.bt38FbmEventSessionRefreshInstalled) return;
  window.bt38FbmEventSessionRefreshInstalled = true;
})();
