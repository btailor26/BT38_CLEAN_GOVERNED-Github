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

    function focusConnectionCardFromLegacyControl(control) {
        const card = document.getElementById('royalMailConnectionCard');
        const form = document.getElementById('royalMailConnectForm');
        if (!card || !form) return false;
        const legacyModal = control && control.closest ? control.closest('.modal') : null;
        if (legacyModal) {
            const close = legacyModal.querySelector('[data-bs-dismiss="modal"], .btn-close');
            if (close) close.click();
        }
        form.classList.remove('d-none');
        card.scrollIntoView({behavior: 'smooth', block: 'center'});
        const apiKey = document.getElementById('royalMailApiKey');
        window.setTimeout(() => { if (apiKey) apiKey.focus(); }, 150);
        return true;
    }

    document.addEventListener('click', async event => {
        const clicked = event.target && event.target.closest ? event.target.closest('button, a') : null;
        if (clicked && clicked.id !== 'royalMailConnect' && (clicked.dataset.bt38RoyalMailConnect === '1' || String(clicked.textContent || '').trim() === 'Connect Royal Mail account')) {
            event.preventDefault();
            event.stopPropagation();
            focusConnectionCardFromLegacyControl(clicked);
            return;
        }

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

    retireLegacyRoyalMailApprovalUi();
    if (document.getElementById('royalMailConnectionCard')) loadState();
})(window, document);
