/* Royal Mail Click & Drop merchant connection.
 *
 * Royal Mail's public API authenticates with the Click & Drop API auth key,
 * not the normal Royal Mail website password. This UI therefore never asks for
 * or stores a Royal Mail password.
 */
(function (window, document) {
    'use strict';

    function esc(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
    }

    async function jsonFetch(url, options) {
        const response = await fetch(url, Object.assign({
            credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'}
        }, options || {}));
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.success === false) {
            const error = new Error(payload.message || `Request failed (${response.status})`);
            error.payload = payload;
            throw error;
        }
        return payload;
    }

    function cardHtml() {
        return `<div class="card fbm-ops-card h-100" id="royalMailConnectionCard">
            <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
                <div><strong>Royal Mail · Click & Drop</strong>
                    <div class="small text-muted">Merchant-owned Royal Mail label and tracking connection.</div>
                </div>
                <span id="royalMailConnectionBadge" class="badge bg-secondary">Checking…</span>
            </div>
            <div class="card-body">
                <div id="royalMailConnectionStatus" class="small text-muted mb-2">Checking connection…</div>
                <div id="royalMailConnectForm" class="d-none">
                    <div class="small text-muted mb-2">Royal Mail's API uses your Click & Drop API auth key, not your normal website password.</div>
                    <div class="row g-2">
                        <div class="col-md-5"><input id="royalMailAccountEmail" class="form-control form-control-sm" type="email" autocomplete="email" placeholder="Royal Mail account email"></div>
                        <div class="col-md-7"><input id="royalMailApiKey" class="form-control form-control-sm" type="password" autocomplete="off" placeholder="Click & Drop API auth key"></div>
                    </div>
                    <div class="d-flex gap-2 mt-2 flex-wrap">
                        <button id="royalMailConnect" class="btn btn-sm btn-primary" type="button">Connect Royal Mail</button>
                        <a class="btn btn-sm btn-outline-secondary" href="https://business.parcel.royalmail.com/" target="_blank" rel="noopener noreferrer">Open Click & Drop</a>
                    </div>
                    <div class="small text-muted mt-2">In Click & Drop: Settings → Integrations → Click & Drop API → copy the authorisation key.</div>
                </div>
                <div id="royalMailConnectedActions" class="d-none d-flex gap-2 flex-wrap">
                    <button id="royalMailTest" class="btn btn-sm btn-outline-primary" type="button">Test connection</button>
                </div>
            </div>
        </div>`;
    }

    function installCard() {
        const grid = document.querySelector('.fbm-top-grid');
        if (!grid || document.getElementById('royalMailConnectionCard')) return false;
        grid.insertAdjacentHTML('beforeend', cardHtml());
        return true;
    }

    function setState(connection) {
        const badge = document.getElementById('royalMailConnectionBadge');
        const status = document.getElementById('royalMailConnectionStatus');
        const form = document.getElementById('royalMailConnectForm');
        const actions = document.getElementById('royalMailConnectedActions');
        if (!badge || !status || !form || !actions) return;

        if (connection && connection.connected) {
            badge.className = 'badge bg-success';
            badge.textContent = 'Connected';
            status.className = 'small text-success mb-2';
            status.textContent = `Connected${connection.account_email ? ' · ' + connection.account_email : ''}`;
            form.classList.add('d-none');
            actions.classList.remove('d-none');
        } else {
            badge.className = 'badge bg-secondary';
            badge.textContent = connection?.status === 'auth_error' ? 'Needs attention' : 'Not connected';
            status.className = connection?.status === 'auth_error' ? 'small text-danger mb-2' : 'small text-muted mb-2';
            status.textContent = connection?.last_error || 'Connect this BT38 user to their own Royal Mail Click & Drop account.';
            form.classList.remove('d-none');
            actions.classList.add('d-none');
        }
    }

    async function loadState() {
        try {
            const payload = await jsonFetch('/governed/royal-mail/connection');
            setState(payload.connection || {});
        } catch (error) {
            const status = document.getElementById('royalMailConnectionStatus');
            if (status) {
                status.className = 'small text-danger mb-2';
                status.textContent = error.message;
            }
        }
    }

    document.addEventListener('click', async event => {
        const connect = event.target.closest('#royalMailConnect');
        if (connect) {
            const email = document.getElementById('royalMailAccountEmail')?.value.trim() || '';
            const apiKey = document.getElementById('royalMailApiKey')?.value.trim() || '';
            if (!apiKey) {
                window.alert('Enter the Click & Drop API auth key.');
                return;
            }
            connect.disabled = true;
            try {
                const payload = await jsonFetch('/governed/royal-mail/connection', {
                    method: 'POST',
                    body: JSON.stringify({account_email: email || null, api_key: apiKey})
                });
                document.getElementById('royalMailApiKey').value = '';
                setState(payload.connection || {});
            } catch (error) {
                window.alert(error.message);
            } finally {
                connect.disabled = false;
            }
            return;
        }

        const test = event.target.closest('#royalMailTest');
        if (test) {
            test.disabled = true;
            try {
                const payload = await jsonFetch('/governed/royal-mail/connection/test', {method: 'POST', body: '{}'});
                setState(payload.connection || {});
            } catch (error) {
                window.alert(error.message);
                loadState();
            } finally {
                test.disabled = false;
            }
        }
    });

    if (installCard()) loadState();
    else window.setTimeout(() => { if (installCard()) loadState(); }, 250);
})(window, document);
