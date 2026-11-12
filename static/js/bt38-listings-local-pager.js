// Listings page: one browser-local bottom pager for the already rendered dataset.
// Never requests the server when the operator changes page or page size.
(function () {
  'use strict';
  function init() {
    const table = document.getElementById('bt38ListingsTable');
    const size = document.getElementById('bt38ListingsPageSize');
    const previous = document.getElementById('bt38ListingsPrev');
    const next = document.getElementById('bt38ListingsNext');
    const label = document.getElementById('bt38ListingsPageLabel');
    const count = document.getElementById('bt38ListingsCount');
    if (!table || !size || !previous || !next || !label || !count) return;
    const rows = Array.from(table.querySelectorAll('tbody > tr'));
    let page = 1;
    function render() {
      const perPage = [15, 25, 50, 100].includes(Number(size.value)) ? Number(size.value) : 15;
      const pages = Math.max(1, Math.ceil(rows.length / perPage));
      page = Math.max(1, Math.min(page, pages));
      const start = (page - 1) * perPage;
      rows.forEach((row, index) => { row.hidden = index < start || index >= start + perPage; });
      count.textContent = 'Showing ' + (rows.length ? start + 1 : 0) + '–' + Math.min(start + perPage, rows.length) + ' of ' + rows.length + ' records';
      label.textContent = 'Page ' + page + ' of ' + pages + ' · ' + rows.length + ' total';
      previous.disabled = page === 1;
      next.disabled = page === pages;
    }
    size.addEventListener('change', () => { page = 1; render(); });
    previous.addEventListener('click', () => { page -= 1; render(); });
    next.addEventListener('click', () => { page += 1; render(); });
    render();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
