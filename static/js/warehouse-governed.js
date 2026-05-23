// BT38 warehouse page governed shortcut wiring.
// Single frontend shortcut layer. Authority remains the fuse box/backend.
(function () {
  if (window.bt38WarehouseGovernedInstalled) return;
  window.bt38WarehouseGovernedInstalled = true;

  function warehouseActive() {
    return !!document.querySelector('.bt38-enterprise-stock .bt38-stock-table');
  }

  function validListingId(value) {
    const v = String(value ?? '').trim();
    return v !== '' && v !== '0' && v.toLowerCase() !== 'null' && v.toLowerCase() !== 'undefined';
  }

  function selectedRows() {
    return Array.from(document.querySelectorAll('.bt38-row-select:checked'));
  }

  function postJson(endpoint, body) {
    const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
    return fetch(endpoint, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-CSRF-Token': csrf
      },
      body: JSON.stringify(body || {})
    }).then(async function (response) {
      const data = await response.json().catch(function () { return {}; });
      if (!response.ok || data.success === false || data.ok === false) {
        throw new Error(data.reason || data.error || data.message || 'Governed action failed.');
      }
      return data;
    });
  }

  function governedDisabled(message) {
    alert(message || 'This action is disabled until the governed route is approved.');
    return Promise.resolve({ ok: false, success: false, governed: true, execution_blocked: true, message: message || 'This action is disabled until the governed route is approved.' });
  }

  function updateActionBar() {
    const selected = selectedRows();
    const bar = document.getElementById('bt38FloatingActionBar');
    const count = document.getElementById('bt38SelectedCount');
    if (!bar || !count) return;
    count.textContent = selected.length;
    if (selected.length > 0) {
      bar.hidden = false;
    } else {
      bar.hidden = true;
      const select = document.getElementById('bt38ActionSelect');
      if (select) select.value = '';
    }
  }

  function clearSelection() {
    document.querySelectorAll('.bt38-row-select').forEach(function (cb) { cb.checked = false; });
    updateActionBar();
  }

  function pushGovernedListing(row) {
    if (!row) return Promise.reject(new Error('Missing row for governed push.'));
    const listingId = row.dataset.listingId || '';
    const sku = row.dataset.sku || '';
    if (!validListingId(listingId)) {
      return Promise.reject(new Error('Missing valid marketplace listing id for ' + (sku || 'this row') + '.'));
    }
    return postJson('/governed/actions/listings/' + encodeURIComponent(listingId) + '/push', {});
  }

  function runWarehouseSync() {
    const btn = document.getElementById('governedWarehouseSyncBtn');
    const original = btn ? btn.innerHTML : '';
    if (btn) { btn.disabled = true; btn.innerHTML = 'Syncing...'; }
    return postJson('/governed/warehouse/sync', {})
      .then(function (data) {
        if (btn) btn.innerHTML = 'Synced (' + (data.pushed || 0) + ')';
        setTimeout(function () { window.location.reload(); }, 1200);
        return data;
      })
      .catch(function (err) {
        if (btn) btn.innerHTML = 'Sync Failed';
        alert('Governed warehouse sync failed: ' + err.message);
      })
      .finally(function () {
        if (btn) setTimeout(function () { btn.disabled = false; btn.innerHTML = original; }, 3000);
      });
  }

  function chooseAction(value) {
    if (!value) return;
    const selected = selectedRows();
    if (!selected.length) return alert('Select at least one SKU first.');

    if (value === 'sync') {
      if (confirm('Run governed warehouse sync? Fuse box/settings will decide if it is allowed.')) runWarehouseSync();
      return;
    }

    if (value !== 'push') {
      alert('Only governed Push and governed Warehouse Sync are wired here. Other actions remain disabled until approved.');
      const select = document.getElementById('bt38ActionSelect');
      if (select) select.value = '';
      return;
    }

    const validRows = [];
    const invalidRows = [];
    selected.forEach(function (cb) {
      const row = cb.closest('tr');
      if (row && validListingId(row.dataset.listingId)) validRows.push(row);
      else invalidRows.push(row);
    });

    if (!validRows.length) return alert('No selected rows have a valid marketplace listing id. Nothing was pushed.');
    if (!confirm('Run governed push for ' + validRows.length + ' selected SKU(s)? Invalid rows skipped: ' + invalidRows.length)) return;

    Promise.allSettled(validRows.map(pushGovernedListing)).then(function (results) {
      const passed = results.filter(function (r) { return r.status === 'fulfilled'; }).length;
      const failed = results.length - passed;
      alert('Governed push complete. Success: ' + passed + '. Failed: ' + failed + '. Skipped invalid rows: ' + invalidRows.length + '.');
      window.location.reload();
    });
  }

  function openRowAction(button) {
    const row = button && button.closest ? button.closest('tr') : null;
    if (!row) return false;
    const itemId = row.dataset.itemId || '';
    const stockId = row.dataset.stockId || '';
    const listingId = row.dataset.listingId || '';
    const sku = row.dataset.sku || '';

    if (button.classList.contains('bt38-marketplace-control')) {
      if (!validListingId(listingId)) { alert('This row has no valid marketplace listing id. Import/link this SKU before pushing.'); return false; }
      if (!confirm('Run governed marketplace push for ' + (sku || listingId) + '? Fuse box/settings will decide if it is allowed.')) return false;
      pushGovernedListing(row).then(function (data) {
        alert(data.reason || data.message || 'Governed marketplace push completed.');
        window.location.reload();
      }).catch(function (err) { alert('Governed marketplace push failed: ' + err.message); });
      return false;
    }

    if (button.classList.contains('bt38-qty-action')) {
      if (!validListingId(listingId)) { governedDisabled('This row has no valid marketplace listing id for governed quantity update.'); return false; }
      const current = button.querySelector('span')?.innerText?.trim() || '0';
      const next = prompt('New quantity for ' + sku + ':', current);
      if (next === null) return false;
      const qty = parseInt(next, 10);
      if (Number.isNaN(qty) || qty < 0) return alert('Enter a valid quantity.');
      postJson('/governed/actions/listings/' + encodeURIComponent(listingId) + '/quantity', { quantity: qty })
        .then(function (data) { alert(data.message || data.reason || 'Governed quantity saved.'); window.location.reload(); })
        .catch(function (err) { alert('Quantity update failed: ' + err.message); });
      return false;
    }

    if (button.classList.contains('bt38-price-action')) {
      if (!validListingId(listingId)) { governedDisabled('This row has no valid marketplace listing id for governed price update.'); return false; }
      const current = button.querySelector('span')?.innerText?.replace(/[^\d.]/g, '') || '0.00';
      const next = prompt('New price for ' + sku + ':', current);
      if (next === null) return false;
      postJson('/governed/actions/listings/' + encodeURIComponent(listingId) + '/price', { price: next })
        .then(function (data) { alert(data.message || data.reason || 'Governed price saved.'); window.location.reload(); })
        .catch(function (err) { alert('Price update failed: ' + err.message); });
      return false;
    }

    if (button.classList.contains('bt38-warehouse-action')) {
      window.location.href = '/warehouse?q=' + encodeURIComponent(sku || stockId || itemId);
      return false;
    }

    if (button.classList.contains('bt38-action-btn')) {
      alert('Use the marketplace icon for governed single push, Qty Save for governed quantity, or row select for bulk governed push.');
      return false;
    }

    return false;
  }

  window.bt38SelectedRows = selectedRows;
  window.bt38UpdateActionBar = updateActionBar;
  window.bt38ClearSelection = clearSelection;
  window.bt38ChooseAction = chooseAction;
  window.bt38OpenRowAction = openRowAction;
  window.bt38PushGovernedListing = pushGovernedListing;
  window.bt38RunGovernedWarehouseSync = runWarehouseSync;
  window.bt38ValidListingId = validListingId;

  document.addEventListener('DOMContentLoaded', function () {
    if (!warehouseActive()) return;
    document.querySelectorAll('.bt38-row-select').forEach(function (cb) { cb.addEventListener('change', updateActionBar); });
    const syncBtn = document.getElementById('governedWarehouseSyncBtn');
    if (syncBtn) syncBtn.addEventListener('click', function () {
      if (confirm('Run governed warehouse sync? Fuse box/settings will decide if it is allowed.')) runWarehouseSync();
    });
  });
})();
