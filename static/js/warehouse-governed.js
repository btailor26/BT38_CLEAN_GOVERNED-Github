(function () {
  "use strict";

  function getRowFromElement(element) {
    if (!element) return null;
    return element.closest("tr");
  }

  function getListingId(row) {
    if (!row || !row.dataset) return "";
    return String(row.dataset.listingId || "").trim();
  }

  function getStockId(row) {
    if (!row || !row.dataset) return "";
    return String(row.dataset.stockId || "").trim();
  }

  function getSku(row) {
    if (!row || !row.dataset) return "";
    return String(row.dataset.sku || "").trim();
  }

  function validListingId(listingId) {
    return !!listingId && listingId !== "0" && listingId !== "null" && listingId !== "undefined";
  }

  async function postJson(url, payload, actor) {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Actor": actor || "warehouse-governed-js"
      },
      body: JSON.stringify(payload || {})
    });

    const data = await response.json().catch(function () {
      return {
        ok: false,
        success: false,
        message: "Invalid JSON response from governed route."
      };
    });

    if (!response.ok || !(data.ok || data.success)) {
      const message = data.message || data.error || data.reason || "Governed action failed.";
      throw new Error(message);
    }

    return data;
  }

  function setButtonBusy(button, text) {
    if (!button) return;
    if (!button.dataset.originalText) {
      button.dataset.originalText = button.textContent || "";
    }
    button.disabled = true;
    button.textContent = text || "Working...";
  }

  function resetButton(button) {
    if (!button) return;
    button.disabled = false;
    if (button.dataset.originalText) {
      button.textContent = button.dataset.originalText;
    }
  }

  function readQuantityFromButton(button) {
    const parentText = button && button.parentElement ? button.parentElement.innerText || "" : "";
    const match = parentText.match(/-?\d+/);
    return match ? match[0] : "0";
  }

  function readPriceFromButton(button) {
    const parentText = button && button.parentElement ? button.parentElement.innerText || "" : "";
    const cleaned = parentText.replace(/[^\d.]/g, "");
    return cleaned || "0.00";
  }

  async function pushGovernedListing(row, actor) {
    const listingId = getListingId(row);

    if (!validListingId(listingId)) {
      throw new Error("This row has no governed marketplace listing id.");
    }

    return postJson(
      "/governed/actions/listings/" + encodeURIComponent(listingId) + "/push",
      {},
      actor || "warehouse-row-push"
    );
  }

  async function saveGovernedQuantity(row, quantity, actor) {
    const listingId = getListingId(row);

    if (!validListingId(listingId)) {
      throw new Error("This row has no governed marketplace listing id for quantity update.");
    }

    return postJson(
      "/governed/actions/listings/" + encodeURIComponent(listingId) + "/quantity",
      { quantity: quantity },
      actor || "warehouse-row-quantity"
    );
  }

  async function saveGovernedPrice(row, price, actor) {
    const listingId = getListingId(row);

    if (!validListingId(listingId)) {
      throw new Error("This row has no governed marketplace listing id for price update.");
    }

    return postJson(
      "/governed/actions/listings/" + encodeURIComponent(listingId) + "/price",
      { price: price },
      actor || "warehouse-row-price"
    );
  }

  async function openRowAction(button) {
    const row = getRowFromElement(button);

    if (!row) {
      alert("No warehouse row found for this action.");
      return false;
    }

    const sku = getSku(row);
    const stockId = getStockId(row);

    try {
      if (button.classList.contains("bt38-marketplace-control")) {
        setButtonBusy(button, "Pushing...");
        const data = await pushGovernedListing(row, "warehouse-row-push-button");
        setButtonBusy(button, "Done");
        console.log("Governed marketplace push result", data);
        setTimeout(function () { resetButton(button); }, 1200);
        return false;
      }

      if (button.classList.contains("bt38-qty-action")) {
        const currentQty = readQuantityFromButton(button);
        const nextQty = prompt("Enter new warehouse quantity for " + (sku || stockId), currentQty);

        if (nextQty === null || nextQty === "") return false;

        setButtonBusy(button, "Saving...");
        const data = await saveGovernedQuantity(row, nextQty, "warehouse-row-quantity-button");
        console.log("Governed quantity result", data);
        setButtonBusy(button, "Saved");
        setTimeout(function () { window.location.reload(); }, 700);
        return false;
      }

      if (button.classList.contains("bt38-price-action")) {
        const currentPrice = readPriceFromButton(button);
        const nextPrice = prompt("Enter new local listing price for " + (sku || stockId), currentPrice);

        if (nextPrice === null || nextPrice === "") return false;

        setButtonBusy(button, "Saving...");
        const data = await saveGovernedPrice(row, nextPrice, "warehouse-row-price-button");
        console.log("Governed price result", data);
        setButtonBusy(button, "Saved");
        setTimeout(function () { window.location.reload(); }, 700);
        return false;
      }

      if (button.classList.contains("bt38-warehouse-action")) {
        window.location.href = "/warehouse?q=" + encodeURIComponent(sku || stockId);
        return false;
      }

      window.location.href = "/warehouse?q=" + encodeURIComponent(sku || stockId);
      return false;
    } catch (error) {
      console.error(error);
      alert(error.message || "Governed warehouse action failed.");
      resetButton(button);
      return false;
    }
  }

  async function chooseAction(value) {
    if (!value) return false;

    const select = document.getElementById("bt38ActionSelect");
    const selected = Array.from(document.querySelectorAll(".bt38-row-check:checked"));
    const rows = selected.map(function (checkbox) {
      return checkbox.closest("tr");
    }).filter(Boolean);

    if (!rows.length) {
      if (select) select.value = "";
      alert("Select at least one SKU first.");
      return false;
    }

    if (value !== "push" && value !== "sync") {
      if (select) select.value = "";
      alert("Only governed Push/Sync shortcuts are enabled on this page.");
      return false;
    }

    if (!confirm("Run governed " + value + " for " + rows.length + " selected SKU(s)?")) {
      if (select) select.value = "";
      return false;
    }

    try {
      let passed = 0;
      let failed = 0;

      for (const row of rows) {
        try {
          await pushGovernedListing(row, "warehouse-bulk-" + value);
          passed += 1;
        } catch (error) {
          failed += 1;
          console.error("Bulk governed action failed", error);
        }
      }

      alert("Governed " + value + " complete. Success: " + passed + ". Failed: " + failed + ".");
      window.location.reload();
    } finally {
      if (select) select.value = "";
    }

    return false;
  }

  async function runWarehouseSync() {
    const button = document.getElementById("governedWarehouseSyncBtn");

    if (!button) {
      alert("Governed warehouse sync button was not found.");
      return false;
    }

    try {
      setButtonBusy(button, "Syncing...");
      const data = await postJson("/governed/warehouse/sync", {}, "warehouse-sync-button");
      console.log("Governed warehouse sync result", data);
      setButtonBusy(button, "Synced");
      setTimeout(function () { window.location.reload(); }, 900);
    } catch (error) {
      console.error(error);
      alert(error.message || "Governed warehouse sync failed.");
      resetButton(button);
    }

    return false;
  }

  function interceptLegacyUpdateStockForms(event) {
    const form = event.target;

    if (!form || !form.action || !form.action.includes("/update_stock/")) return;

    event.preventDefault();

    const row = form.closest("tr");

    if (!row) {
      alert("Quantity update blocked: no warehouse row was found.");
      return;
    }

    const input =
      form.querySelector('input[name="quantity"]') ||
      form.querySelector('input[name="available_quantity"]') ||
      form.querySelector('input[type="number"]');

    const quantity = input ? input.value : prompt("Enter new quantity");

    if (quantity === null || quantity === "") return;

    saveGovernedQuantity(row, quantity, "warehouse-legacy-update-stock-intercept")
      .then(function (data) {
        console.log("Governed quantity shortcut result", data);
        alert(data.message || "Warehouse quantity saved through governed fuse box.");
        window.location.reload();
      })
      .catch(function (error) {
        console.error(error);
        alert("Quantity update failed: " + (error.message || error));
      });
  }

  function bindSyncButton() {
    const button = document.getElementById("governedWarehouseSyncBtn");
    if (!button) return;
    button.addEventListener("click", function (event) {
      event.preventDefault();
      runWarehouseSync();
    });
  }

  window.bt38OpenRowAction = openRowAction;
  window.bt38ChooseAction = chooseAction;
  window.bt38PushGovernedListing = pushGovernedListing;

  document.addEventListener("submit", interceptLegacyUpdateStockForms, true);
  document.addEventListener("DOMContentLoaded", bindSyncButton);
})();
