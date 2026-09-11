// Compact COFI controls for the existing BT38 owner fuse board.
// No new page and no second settings authority: values persist in SystemConfig.
(function () {
  "use strict";

  const root = document.querySelector('[data-bt38-page="settings"]');
  if (!root || document.getElementById("bt38CofiSettings")) return;

  function log(data) {
    if (typeof window.bt38Log === "function") window.bt38Log(data);
  }

  function toggleCell(key, checked, label) {
    const wrapper = document.createElement("label");
    wrapper.className = "bt38-toggle";

    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = Boolean(checked);
    input.dataset.cofiKey = key;
    input.setAttribute("aria-label", label);

    const slider = document.createElement("span");
    const badge = document.createElement("b");
    badge.className = input.checked ? "on" : "off";
    badge.textContent = input.checked ? "ON" : "OFF";

    wrapper.append(input, slider, badge);
    return wrapper;
  }

  async function save(input) {
    const oldValue = !input.checked;
    input.disabled = true;
    try {
      const response = await fetch("/governed/settings/cofi", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json",
          "X-Actor": "settings-cockpit"
        },
        body: JSON.stringify({key: input.dataset.cofiKey, value: input.checked})
      });
      const data = await response.json();
      if (!response.ok || data.success === false) {
        throw new Error(data.error || data.message || "COFI setting update failed");
      }
      const badge = input.parentElement.querySelector("b");
      if (badge) {
        badge.className = input.checked ? "on" : "off";
        badge.textContent = input.checked ? "ON" : "OFF";
      }
      log({ok: true, success: true, message: `COFI control updated: ${input.dataset.cofiKey}`});
    } catch (error) {
      input.checked = oldValue;
      const badge = input.parentElement.querySelector("b");
      if (badge) {
        badge.className = input.checked ? "on" : "off";
        badge.textContent = input.checked ? "ON" : "OFF";
      }
      log({ok: false, success: false, error: String(error.message || error)});
    } finally {
      input.disabled = false;
    }
  }

  function render(controls) {
    const section = document.createElement("div");
    section.className = "bt38-section";
    section.id = "bt38CofiSettings";
    section.innerHTML = `
      <h3>COFI Controls</h3>
      <div class="bt38-section-note">One compact control layer for COFI. These switches grant permission only; they do not create a second worker, sync path or marketplace write path.</div>
      <table class="bt38-table">
        <thead><tr><th>Master</th><th>Opportunity Analysis</th><th>Customer Visibility</th></tr></thead>
        <tbody><tr id="bt38CofiControlRow"></tr></tbody>
      </table>`;

    const row = section.querySelector("#bt38CofiControlRow");
    const cells = [
      ["cofi_enabled", controls.cofi_enabled, "COFI master"],
      ["cofi_opportunities_enabled", controls.cofi_opportunities_enabled, "COFI opportunity analysis"],
      ["cofi_customer_visibility_enabled", controls.cofi_customer_visibility_enabled, "COFI customer visibility"]
    ];

    cells.forEach(([key, checked, label]) => {
      const td = document.createElement("td");
      td.appendChild(toggleCell(key, checked, label));
      row.appendChild(td);
    });

    section.querySelectorAll("input[data-cofi-key]").forEach((input) => {
      input.addEventListener("change", () => save(input));
    });

    const sections = Array.from(root.querySelectorAll(":scope > .bt38-section"));
    const limits = sections.find((item) => item.querySelector("h3")?.textContent.trim().includes("Limits + Safety"));
    if (limits) root.insertBefore(section, limits);
    else root.appendChild(section);
  }

  async function load() {
    try {
      const response = await fetch("/governed/settings/cofi", {
        credentials: "include",
        headers: {"Accept": "application/json"},
        cache: "no-store"
      });
      const data = await response.json();
      if (!response.ok || data.success === false) return;
      render(data.controls || {});
    } catch (error) {
      console.warn("[COFI settings] controls unavailable", error);
    }
  }

  load();
})();
