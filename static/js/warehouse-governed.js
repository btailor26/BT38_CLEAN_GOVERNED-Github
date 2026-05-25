// BT38 warehouse page governed shortcut controller.
// Single frontend authority for warehouse row and bulk actions.
// Pages/buttons are shortcuts only; backend fuse box decides execution.
(function () {
  'use strict';

  function warehouseActive() {
    return !!document.querySelector('.bt38-enterprise-stock .bt38-stock-table');
  }

  function selectedRows() {
    return Array.from(document.querySelectorAll('.bt38-row-select:checked'));
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
    document.querySelectorAll('.bt38-row-select').forEach(function (cb) {
      cb.checked = false;
    });
    updateActionBar();
  }

  function postJson(endpoint, body, actor) {
    const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
    return fetch(endpoint, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-CSRF-Token': csrf,
        'X-Actor': actor || 'warehouse-governed-shortcut'
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

  function rowListingId(row) {
    return row ? (row.dataset.listingId || '') : '';
  }

  function rowSku(row) {
    return row ? (row.dataset.sku || '') : '';
  }

  function rowStockId(row) {
    return row ? (row.dataset.stockId || '') : '';
  }

  function setButtonState(btn, label) {
    if (!btn) return;
    if (!btn.dataset.originalText) btn.dataset.originalText = btn.textContent.trim();
    btn.textContent = label;
    btn.disabled = true;
  }

  function resetButton(btn) {
    if (!btn) return;
    if (btn.dataset.originalText) btn.textContent = btn.dataset.originalText;
    btn.disabled = false;
  }

  function guardedDisabled(message) {
    alert(message || 'This action is disabled until the governed route is approved.');
    return Promise.resolve({
      ok: false,
      success: false,
      governed: true,
      execution_blocked: true,
      message: message || 'This action is disabled until the governed route is approved.'
    });
  }

  function pushGovernedListing(row) {
    const listingId = rowListingId(row);
    const sku = rowSku(row);
    if (!listingId || listingId === '0') {
      return Promise.reject(new Error('Missing marketplace listing id for ' + (sku || 'this row') + '.'));
    }
    return postJson('/governed/actions/listings/' + encodeURIComponent(listingId) + '/push', {}, 'warehouse-single-push-shortcut');
  }

  function saveGovernedQuantity(row, quantity) {
    const listingId = rowListingId(row);
    if (!listingId || listingId === '0') {
      return Promise.reject(new Error('Missing marketplace listing id for governed quantity save.'));
    }
    return postJson('/governed/actions/listings/' + encodeURIComponent(listingId) + '/quantity', { quantity: quantity }, 'warehouse-quantity-shortcut');
  }

  function saveGovernedPrice(row, price) {
    const listingId = rowListingId(row);
    if (!listingId || listingId === '0') {
      return Promise.reject(new Error('Missing marketplace listing id for governed price save.'));
    }
    return postJson('/governed/actions/listings/' + encodeURIComponent(listingId) + '/price', { price: price }, 'warehouse-price-shortcut');
  }

  function convertRowToFbm(row) {
    const stockId = rowStockId(row);
    const listingId = rowListingId(row);
    const sku = rowSku(row);

    if (!stockId || stockId === '0') {
      return Promise.reject(new Error('Missing warehouse stock id for ' + (sku || 'this row') + '.'));
    }

    return postJson('/governed/warehouse/stock-transfer/convert-to-fbm', {
      warehouse_stock_id: stockId,
      listing_id: listingId || null,
      reason: 'Warehouse Convert to FBM action',
      notes: 'Created from warehouse governed transfer shortcut.'
    }, 'warehouse-convert-to-fbm-shortcut');
  }

  async function chooseAction(value) {
    if (!value) return;

    const select = document.getElementById('bt38ActionSelect');
    const selected = selectedRows();

    if (!selected.length) {
      if (select) select.value = '';
      alert('Select at least one SKU first.');
      return;
    }

    if (value === 'transfer') {
      if (!confirm('Convert ' + selected.length + ' selected SKU(s) to FBM warehouse-controlled stock?')) {
        if (select) select.value = '';
        return;
      }

      try {
        const results = await Promise.allSettled(selected.map(function (cb) {
          return convertRowToFbm(cb.closest('tr'));
        }));
        const passed = results.filter(function (result) { return result.status === 'fulfilled'; }).length;
        const failed = results.length - passed;
        alert('Governed stock transfer complete. Converted: ' + passed + '. Failed: ' + failed + '.');
        window.location.reload();
      } finally {
        if (select) select.value = '';
      }
      return;
    }

    if (value !== 'push') {
      if (select) select.value = '';
      await guardedDisabled('Only governed Push and Transfer are enabled on this page. Other actions remain blocked until approved.');
      return;
    }

    if (!confirm('Run governed push for ' + selected.length + ' selected SKU(s)?')) {
      if (select) select.value = '';
      return;
    }

    try {
      const results = await Promise.allSettled(selected.map(function (cb) {
        return pushGovernedListing(cb.closest('tr'));
      }));
      const passed = results.filter(function (result) { return result.status === 'fulfilled'; }).length;
      const failed = results.length - passed;
      alert('Governed push complete. Success: ' + passed + '. Failed: ' + failed + '.');
      window.location.reload();
    } finally {
      if (select) select.value = '';
    }
  }

  async function openRowAction(button) {
    const row = button && button.closest ? button.closest('tr') : null;
    if (!row) return false;

    const sku = rowSku(row);
    const stockId = rowStockId(row);

    try {
      if (button.classList.contains('bt38-marketplace-control')) {
        if (!confirm('Run governed marketplace push for ' + (sku || 'this SKU') + '?')) return false;
        setButtonState(button, 'Pushing...');
        const data = await pushGovernedListing(row);
        alert(data.reason || data.message || 'Governed marketplace push completed.');
        window.location.reload();
        return false;
      }

      if (button.classList.contains('bt38-qty-action')) {
        const current = button.querySelector('span')?.innerText?.trim() || '0';
        const next = prompt('New quantity for ' + (sku || 'this SKU') + ':', current);
        if (next === null) return false;

        const qty = parseInt(next, 10);
        if (Number.isNaN(qty) || qty < 0) {
          alert('Enter a valid quantity.');
          return false;
        }

        setButtonState(button, 'Saving...');
        await saveGovernedQuantity(row, qty);
        window.location.reload();
        return false;
      }

      if (button.classList.contains('bt38-price-action')) {
        const current = (button.querySelector('span')?.innerText || '').replace(/[^\d.]/g, '') || '0.00';
        const next = prompt('New local listing price for ' + (sku || 'this SKU') + ':', current);
        if (next === null) return false;

        const price = parseFloat(next);
        if (Number.isNaN(price) || price < 0) {
          alert('Enter a valid price.');
          return false;
        }

        setButtonState(button, 'Saving...');
        await saveGovernedPrice(row, price);
        window.location.reload();
        return false;
      }

      if (button.classList.contains('bt38-warehouse-action') || button.classList.contains('bt38-action-btn')) {
        if (!confirm('Convert ' + (sku || 'this SKU') + ' to FBM warehouse-controlled stock?')) return false;
        setButtonState(button, 'Transferring...');
        const data = await convertRowToFbm(row);
        alert(data.reason || data.message || 'Governed stock transfer recorded.');
        window.location.reload();
        return false;
      }

      return false;
    } catch (err) {
      console.error(err);
      alert(err.message || 'Governed warehouse action failed.');
      resetButton(button);
      return false;
    }
  }

  async function runGovernedWarehouseSync() {
    const btn = document.getElementById('governedWarehouseSyncBtn');
    if (!btn) return;

    const original = btn.textContent;
    try {
      setButtonState(btn, 'Syncing...');
      const data = await postJson('/governed/warehouse/sync', {
        shortcut_source: 'warehouse-sync-all-live-stores',
        store_scope: 'all_active_live_stores'
      }, 'warehouse-sync-all-live-stores');

      const pushed = data.pushed || 0;
      const blocked = data.blocked || 0;
      const failed = data.failed || 0;
      alert(data.message || ('Governed warehouse sync complete. Pushed: ' + pushed + '. Blocked: ' + blocked + '. Failed: ' + failed + '.'));
      window.location.reload();
    } catch (err) {
      console.error(err);
      alert(err.message || 'Governed warehouse sync failed.');
      resetButton(btn);
    } finally {
      setTimeout(function () {
        if (btn && !btn.disabled) return;
        btn.textContent = original || 'Sync Now';
        btn.disabled = false;
      }, 1200);
    }
  }

  window.bt38SelectedRows = selectedRows;
  window.bt38UpdateActionBar = updateActionBar;
  window.bt38ClearSelection = clearSelection;
  window.bt38ChooseAction = chooseAction;
  window.bt38OpenRowAction = openRowAction;
  window.bt38PushGovernedListing = pushGovernedListing;
  window.bt38ConvertRowToFbm = convertRowToFbm;
  window.runGovernedWarehouseSync = runGovernedWarehouseSync;

  document.addEventListener('DOMContentLoaded', function () {
    if (!warehouseActive()) return;

    document.querySelectorAll('.bt38-row-select').forEach(function (cb) {
      cb.addEventListener('change', updateActionBar);
    });

    const syncBtn = document.getElementById('governedWarehouseSyncBtn');
    if (syncBtn) {
      syncBtn.onclick = function (event) {
        event.preventDefault();
        runGovernedWarehouseSync();
      };
    }
  });
})();
