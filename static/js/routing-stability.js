/**
 * SECTION X: URL Freeze / Routing Stability Fix
 * Event-driven session guard: no polling, no idle timers, no timed redirects.
 * No event = no work. Requests are supervised only while an explicit event is active.
 */

(function() {
    'use strict';

    const RoutingStability = {
        config: {
            apiTimeout: 4000,
            dashboardUrl: '/'
        },

        state: {
            loadingOverlayActive: false,
            currentRoute: window.location.pathname,
            failedRoutes: []
        },

        init: function() {
            this.injectStyles();
            this.createLoadingOverlay();
            this.wrapFetch();
            this.setupNavigationMonitor();
            this.logRouteAccess();
            console.log('[RoutingStability] Initialized - event-driven session, idle=sleep');
        },

        injectStyles: function() {
            const style = document.createElement('style');
            style.textContent = `
                #rs-loading-overlay { position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.7);display:none;align-items:center;justify-content:center;z-index:9999;flex-direction:column; }
                #rs-loading-overlay.active { display:flex; }
                #rs-loading-content { text-align:center;color:white;padding:30px;background:#1a1a2e;border-radius:10px;max-width:400px; }
                #rs-loading-spinner { width:50px;height:50px;border:4px solid rgba(255,255,255,.3);border-top-color:#4dabf7;border-radius:50%;animation:rs-spin 1s linear infinite;margin:0 auto 20px; }
                @keyframes rs-spin { to { transform:rotate(360deg); } }
                #rs-loading-message { font-size:16px;margin-bottom:15px; }
                .rs-btn { padding:10px 20px;border:none;border-radius:5px;cursor:pointer;margin:5px;font-size:14px; }
                .rs-btn-primary { background:#4dabf7;color:white; }
                .rs-btn-secondary { background:#6c757d;color:white; }
                .rs-btn:hover { opacity:.9; }
            `;
            document.head.appendChild(style);
        },

        createLoadingOverlay: function() {
            const overlay = document.createElement('div');
            overlay.id = 'rs-loading-overlay';
            overlay.innerHTML = `
                <div id="rs-loading-content">
                    <div id="rs-loading-spinner"></div>
                    <div id="rs-loading-message">Loading...</div>
                    <div id="rs-loading-actions" style="display:none;">
                        <button class="rs-btn rs-btn-primary" onclick="RoutingStability.retryLoad()">Retry</button>
                        <button class="rs-btn rs-btn-secondary" onclick="RoutingStability.goToDashboard()">Go to Dashboard</button>
                    </div>
                </div>`;
            document.body.appendChild(overlay);
        },

        showLoading: function(message) {
            this.state.loadingOverlayActive = true;
            const overlay = document.getElementById('rs-loading-overlay');
            const msgEl = document.getElementById('rs-loading-message');
            const actionsEl = document.getElementById('rs-loading-actions');
            const spinnerEl = document.getElementById('rs-loading-spinner');
            if (overlay) {
                overlay.classList.add('active');
                if (msgEl) msgEl.textContent = message || 'Loading...';
                if (actionsEl) actionsEl.style.display = 'none';
                if (spinnerEl) spinnerEl.style.display = 'block';
            }
        },

        hideLoading: function() {
            this.state.loadingOverlayActive = false;
            const overlay = document.getElementById('rs-loading-overlay');
            if (overlay) overlay.classList.remove('active');
        },

        showLoadingError: function(message) {
            const msgEl = document.getElementById('rs-loading-message');
            const actionsEl = document.getElementById('rs-loading-actions');
            const spinnerEl = document.getElementById('rs-loading-spinner');
            if (msgEl) msgEl.textContent = message || 'Request failed';
            if (actionsEl) actionsEl.style.display = 'block';
            if (spinnerEl) spinnerEl.style.display = 'none';
            this.logRouteFailure(this.state.currentRoute, message);
        },

        retryLoad: function() {
            this.hideLoading();
            if (typeof window.bt38UpdateStateOnly === 'function') window.bt38UpdateStateOnly();
        },

        goToDashboard: function() {
            window.location.href = this.config.dashboardUrl;
        },

        wrapFetch: function() {
            const originalFetch = window.fetch;
            const self = this;
            window.fetch = function(url, options = {}) {
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), self.config.apiTimeout);
                const fetchOptions = { ...options, signal: controller.signal };
                return originalFetch(url, fetchOptions)
                    .then(response => { clearTimeout(timeoutId); return response; })
                    .catch(error => {
                        clearTimeout(timeoutId);
                        if (error.name === 'AbortError') {
                            self.logRouteFailure(url, 'Request timed out after ' + self.config.apiTimeout + 'ms');
                            throw new Error('Request timed out – try again or view jobs tab.');
                        }
                        throw error;
                    });
            };
        },

        setupNavigationMonitor: function() {
            const self = this;
            document.addEventListener('click', function(e) {
                const link = e.target.closest('a[href]');
                if (link && link.href && !link.href.startsWith('javascript:') && !link.target) {
                    const isInternal = link.hostname === window.location.hostname;
                    if (isInternal && !link.href.includes('#')) self.state.currentRoute = new URL(link.href).pathname;
                }
            });
            window.addEventListener('load', function() { self.hideLoading(); });
            window.addEventListener('pagehide', function() { self.hideLoading(); });
        },

        logRouteAccess: function() {
            console.log('[RoutingStability] Route:', window.location.pathname);
        },

        logRouteFailure: function(route, reason) {
            const entry = { route: route, reason: reason, timestamp: new Date().toISOString() };
            this.state.failedRoutes.push(entry);
            console.error('[RoutingStability] Route failure:', entry);
        }
    };

    window.RoutingStability = RoutingStability;
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() { RoutingStability.init(); });
    } else {
        RoutingStability.init();
    }
})();

window.safeApiCall = async function(url, options = {}, fallbackValue = null) {
    try {
        const response = await fetch(url, { credentials: 'same-origin', ...options });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const contentType = response.headers.get('content-type');
        if (contentType && contentType.includes('application/json')) return await response.json();
        return await response.text();
    } catch (error) {
        console.error(`[safeApiCall] Error calling ${url}:`, error);
        return fallbackValue;
    }
};

window.submitBackgroundJob = async function(url, data, successMessage) {
    try {
        RoutingStability.showLoading('Starting background job...');
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
            credentials: 'same-origin'
        });
        RoutingStability.hideLoading();
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || `HTTP ${response.status}`);
        }
        const result = await response.json();
        if ((result.job_id || result.queued || result.success) && successMessage) alert(successMessage);
        return result;
    } catch (error) {
        RoutingStability.hideLoading();
        console.error('[submitBackgroundJob] Error:', error);
        alert('Operation failed: ' + error.message);
        throw error;
    }
};
