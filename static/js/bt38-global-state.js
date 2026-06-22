// ======================================================
// BT38 GLOBAL STATE ENGINE (STABLE CLEAN VERSION)
// ======================================================

window.BT38 = window.BT38 || {};

window.BT38.state = {
  page: null,
  cache: {},
  session: {
    allowFetch: false
  }
};

window.BT38.canFetch = function(context) {
  return window.BT38.state.session.allowFetch === true;
};

window.BT38.fetch = async function(url, options = {}, context = "default") {
  if (!window.BT38.canFetch(context)) {
    console.warn("[BT38 BLOCKED FETCH]", url);
    return null;
  }
  return fetch(url, options);
};

window.BT38.initPage = function(pageName) {
  window.BT38.state.page = pageName;
  window.BT38.state.cache[pageName] = window.BT38.state.cache[pageName] || {};
};

window.BT38.enableFetch = function() {
  window.BT38.state.session.allowFetch = true;
};

window.BT38.disableFetch = function() {
  window.BT38.state.session.allowFetch = false;
};
